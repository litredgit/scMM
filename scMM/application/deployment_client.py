"""Local operator's bounded maintenance client; browser credentials never leave this process."""
# ruff: noqa: RUF001

import argparse
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, suppress
from pathlib import Path

import psutil

from .auth import AuthStore, digest
from .deployment_maintenance import GRACE_SECONDS, SNAPSHOT_SECONDS
from .projects import write_json
from .server_config import load_server_config


@contextmanager
def local_admin(config):
    """An audited, short-lived offline capability for the owner of the private auth DB."""
    store = AuthStore(config.auth_db)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.time()
    created = now - max(0, config.values.get("session_absolute_seconds", 43200) - 600)
    with store.connect() as db:
        account = db.execute(
            "SELECT id FROM users WHERE active=1 AND role='admin' AND must_change=0 ORDER BY id LIMIT 1"
        ).fetchone()
        if account is None:
            raise RuntimeError("部署维护需要已完成初始化的管理员账号。")
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?)",
            (digest(token), account["id"], csrf, created, now),
        )
    try:
        store.audit(
            account["id"], "local_deployment_session", "local OS operator; expires in 10 min"
        )
        yield {
            "Cookie": config.cookie_name + "=" + token,
            "X-SCMM-CSRF": csrf,
            "X-SCMM-Client": "web",
        }
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (digest(token),))


def request(port, headers, path, body=None, timeout=10):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1{path}",
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def worker_states(config):
    roots = [
        Path(config.values["project_root"]),
        *(Path(p) for p in config.values.get("output", {}).values()),
    ]
    states = []
    for root in roots:
        for pattern in (
            "*/processing/*/state.json",
            "*/processing/preview-jobs/*/state.json",
            "*/state.json",
            "*/tasks/*/state.json",
        ):
            for path in root.glob(pattern):
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError("Unsafe task metadata path")
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("status") in {"queued", "running"}:
                    states.append(path)
    return list(dict.fromkeys(states))


def owned_workers(config):
    roots = [
        Path(config.values["project_root"]).resolve(),
        *(Path(p).resolve() for p in config.values.get("output", {}).values()),
    ]
    workers = []
    repository = Path(
        os.environ.get("SCMM_DEPLOY_REPOSITORY", Path(__file__).resolve().parents[2])
    ).resolve()
    for process in psutil.process_iter(["cmdline"]):
        args = process.info["cmdline"] or []
        if not any(
            m in args for m in ("scMM.application.worker", "scMM.application.project_batch")
        ):
            continue
        paths = [Path(a).resolve() for a in args if a.endswith(("state.json", "request.json"))]
        uses_repository = any(a.startswith(str(repository) + "/") for a in args)
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            uses_repository = uses_repository or Path(process.cwd()).is_relative_to(repository)
        if uses_repository or any(p.is_relative_to(root) for p in paths for root in roots):
            workers.append(process)
    return workers


def stop_workers(config):
    """Terminate only identified workers and descendants; never signal a state-file PID."""
    workers = owned_workers(config)
    targets = {p.pid: p for p in workers}
    for process in workers:
        with suppress(psutil.NoSuchProcess):
            targets.update({p.pid: p for p in process.children(recursive=True)})
    for process in targets.values():
        with suppress(psutil.NoSuchProcess):
            process.terminate()
    _, alive = psutil.wait_procs(list(targets.values()), timeout=10)
    for process in alive:
        with suppress(psutil.NoSuchProcess):
            process.kill()
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive or owned_workers(config):
        raise RuntimeError("任务进程尚未退出，不能更新代码。")
    interrupted = []
    # Rewrite only after all identified writers have exited. Preserve completed samples.
    for path in worker_states(config):
        state = json.loads(path.read_text(encoding="utf-8"))
        message = "服务部署维护中断；已完成样本保留，未完成结果不可纳入。"
        if "task_id" in state:
            from .tasks import utc_now

            state.update(
                status="failed", error=message, finished_at=utc_now(), updated_at=utc_now()
            )
        else:
            state.update(status="interrupted", message=message)
        write_json(path, state)
        interrupted.append(str(path))
    return interrupted


def prepare_service(config, port):
    root = config.path.parent / (config.path.stem + ".recovery")
    root.mkdir(mode=0o700, exist_ok=True)
    with local_admin(config) as headers:

        def call(path, body=None, **kw):
            return request(port, headers, path, body, **kw)

        legacy = False
        try:
            state = call("/admin/maintenance/deployment/prepare", {})
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            # First installation only: old process can collect drafts but has no new policy.
            legacy = True
            state = call("/admin/maintenance/prepare", {})
        for path in worker_states(config):
            (path.parent / "stop.requested").touch()
        deadline = state["request"].get("deadline", time.time() + GRACE_SECONDS)
        while time.time() < deadline:
            time.sleep(min(1, deadline - time.time()))
        interrupted = stop_workers(config)
        if legacy:
            runtime = call("/admin/monitor")
            if not isinstance(runtime.get("requests"), list):
                raise RuntimeError("旧进程缺少正式请求明细，不能安全停止。")
            protected = [
                r
                for r in runtime["requests"]
                if r.get("business")
                and r.get("kind") not in {"分析", "预处理", "原始谱预览", "下载"}
            ]
            if protected:
                raise RuntimeError("旧进程仍有受保护请求，不能安全停止。")
            saved = False
            with suppress(OSError, ValueError):
                saved = bool(
                    call("/admin/maintenance/checkpoint", {}, timeout=SNAPSHOT_SECONDS).get(
                        "completed"
                    )
                )
            report = {
                "legacy": True,
                "discard_pointer": not saved,
                "preserved": saved,
                "interrupted_tasks": len(interrupted),
            }
        else:
            safety_deadline = time.monotonic() + SNAPSHOT_SECONDS
            while True:
                try:
                    call("/admin/maintenance/deployment/checkpoint", {})
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 400 or time.monotonic() >= safety_deadline:
                        raise
                    time.sleep(1)
            deadline = time.monotonic() + SNAPSHOT_SECONDS + 15
            while True:
                state = call("/admin/maintenance/status")
                report = state["deployment"]
                if report["phase"] == "ready":
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("维护控制接口超时；尚未确认正式写入已安全结束。")
                time.sleep(1)
            report = {**report, "interrupted_tasks": len(interrupted), "discard_pointer": False}
        # A request admitted before maintenance may have finished launching a worker.
        interrupted.extend(stop_workers(config))
        report["interrupted_tasks"] = len(interrupted)
        write_json(root / "deployment-release.json", report)
        (root / "deployment-release.json").chmod(0o600)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    config = load_server_config(args.config, environ={}).validate()
    print(json.dumps(prepare_service(config, args.port)))


if __name__ == "__main__":
    main()
