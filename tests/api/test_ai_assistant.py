"""Synthetic upstream requests, privacy, isolation, cancellation and lock independence."""

import asyncio
import json
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scMM.application.ai_client import ChatClient, EndpointPolicy, normalize_url
from scMM.application.ai_config import AIConfigStore, AIError
from scMM.application.workbench import AnalysisWorkspace
from tests.support.workflow import import_data, operation

SYNTHETIC_KEY = "SECRET-KEY-synthetic"

DONE = b'data: {"choices":[{"index":0,"delta":{"content":"synthetic answer"}}]}\n\ndata: [DONE]\n\n'


@pytest.fixture
def ai(workflow, tmp_path, monkeypatch):
    client = workflow[0]
    app = client.app
    app.state.ai_config = AIConfigStore.initialize(
        tmp_path / "private-ai/db.sqlite3", tmp_path / "keys/ai.key"
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    sent = []

    def upstream(request):
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=DONE)

    app.state.ai_client = ChatClient(EndpointPolicy(), transport=httpx.MockTransport(upstream))
    body = {
        "base_url": "https://provider.example/v1",
        "model": "synthetic-model",
        "api_key": SYNTHETIC_KEY,
    }
    response = client.put("/api/v1/ai/config", json=body)
    assert response.status_code == 200, response.text
    return workflow, app, sent, body


def chat(ai, messages=None):
    workflow = ai[0]
    return workflow[0].post(
        "/api/v1/ai/chat",
        headers=workflow[1],
        json={
            "page": "analysis",
            "messages": messages or [{"role": "user", "content": "Explain current result"}],
        },
    )


def context(ai):
    w = ai[0]
    response = w[0].get("/api/v1/ai/context?page=analysis", headers=w[1])
    assert response.status_code == 200, response.text
    return response.json()


def test_encryption_replace_delete_and_relogin(ai, caplog):
    w, app, _, body = ai
    client = w[0]
    store = app.state.ai_config
    identity = client.get("/api/v1/auth/me").json()["id"]
    value = client.get("/api/v1/ai/config").json()
    assert value == {
        "available": True,
        "configured": True,
        "base_url": body["base_url"],
        "model": body["model"],
    }
    assert body["api_key"].encode() not in store.database.read_bytes()
    assert body["base_url"].encode() not in store.database.read_bytes()
    reloaded = AIConfigStore(store.database, Path(ai[0][4]).parent / "keys/ai.key")
    assert reloaded.load(identity)["key"] == body["api_key"]
    assert (
        client.put(
            "/api/v1/ai/config", json={"base_url": "https://other.example/v1", "model": "new"}
        ).status_code
        == 422
    )
    assert store.load(identity)["base_url"] == body["base_url"]
    replacement = {**body, "base_url": "https://other.example/v1", "api_key": "REPLACEMENT"}
    assert client.put("/api/v1/ai/config", json=replacement).status_code == 200
    assert store.load(identity) == {
        "base_url": replacement["base_url"],
        "model": body["model"],
        "key": "REPLACEMENT",
    }
    relogin_password = secrets.token_urlsafe(24)
    credential = app.state.auth.update_user(identity, reset=True)["initial_credential"]
    response = client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": credential}
    )
    client.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    client.post("/api/v1/auth/password", json={"new_password": relogin_password}).raise_for_status()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "tester", "password": relogin_password},
    )
    client.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    assert client.get("/api/v1/ai/config").json()["configured"]
    assert store.load(identity)["key"] == "REPLACEMENT"
    assert client.delete("/api/v1/ai/config").status_code == 200
    assert not client.get("/api/v1/ai/config").json()["configured"]
    assert chat(ai).status_code == 400
    assert body["api_key"] not in caplog.text


def test_user_isolation_and_authenticated_boundary(ai):
    w, app, _, _ = ai
    first = w[0]
    other_password = secrets.token_urlsafe(24)
    created = app.state.auth.create_user("second-user", "member")
    other = TestClient(app, headers={"X-SCMM-Client": "web"})
    response = other.post(
        "/api/v1/auth/login",
        json={"username": "second-user", "password": created["initial_credential"]},
    )
    other.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    other.post("/api/v1/auth/password", json={"new_password": other_password}).raise_for_status()
    response = other.post(
        "/api/v1/auth/login",
        json={"username": "second-user", "password": other_password},
    )
    other.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    assert not other.get("/api/v1/ai/config").json()["configured"]
    assert other.delete("/api/v1/ai/config").status_code == 200
    assert first.get("/api/v1/ai/config").json()["configured"]
    assert other.get("/api/v1/ai/context?page=analysis", headers=w[1]).status_code == 404
    assert (
        other.post(
            "/api/v1/ai/chat",
            headers=w[1],
            json={"page": "analysis", "messages": [{"role": "user", "content": "x"}]},
        ).status_code
        == 400
    )
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/ai/config").status_code == 401
    assert (
        first.put("/api/v1/ai/config", headers={"X-SCMM-CSRF": "wrong"}, json=ai[3]).status_code
        == 403
    )
    assert (
        first.put("/api/v1/ai/config", json={**ai[3], "user_id": created["id"]}).status_code == 422
    )
    other.close()
    anonymous.close()


def test_actual_outbound_is_whitelisted_and_test_has_no_context(ai):
    w, _app, sent, body = ai
    import_data(w)
    identity = w[1]["X-SCMM-Workspace"]
    with w[2].access(identity) as workspace:
        project = workspace.project
        project.manifest["name"] = "SENSITIVE_PROJECT"
        project.manifest["description"] = "SENSITIVE_DESCRIPTION"
        data = project.workspace.data
        data.obs["sensitive-custom"] = "SENSITIVE_GROUP"
        data.obs_names = [f"SENSITIVE_CELL_{i}" for i in range(data.n_obs)]
        data.var_names = [f"SENSITIVE_FEATURE_{i}" for i in range(data.n_vars)]
        history = [
            {
                "operation": "reduce",
                "parameters": {
                    "method": "pca",
                    "store_key": "SENSITIVE_KEY",
                    "source": "/SENSITIVE_PATH/raw",
                    "random_state": 12,
                    "n_components": 2,
                    "n_neighbors": "SENSITIVE_STRING",
                },
            }
        ]
        data.uns["scmm_workbench"]["history_json"] = json.dumps(history)
        project.views["analysis"] = {"method": "DRAFT_SENSITIVE", "random_state": 999}
        project.views["figures"] = {"embedding": {"secret": "SENSITIVE_PLOT"}}
        workspace.revision += 1
    response = chat(ai)
    assert response.status_code == 200 and "event: done" in response.text
    payload = json.loads(sent[-1].content)
    encoded = json.dumps(payload)
    assert "SENSITIVE" not in encoded and "DRAFT" not in encoded and "999" not in encoded
    assert body["api_key"] not in encoded and "data_version" in encoded
    assert payload["stream"] is True and set(payload) == {"model", "messages", "stream"}
    assert sent[-1].url.host == "8.8.8.8"
    assert sent[-1].headers["host"] == "provider.example"
    assert sent[-1].extensions["sni_hostname"] == "provider.example"
    assert sent[-1].headers["authorization"] == "Bearer " + body["api_key"]
    assert '"random_state": 12' in encoded.replace('\\"', '"')
    assert "暂无" not in response.text  # mock returned literal text
    assert w[0].post("/api/v1/ai/test").status_code == 200
    test_payload = json.loads(sent[-1].content)
    assert test_payload["messages"] == [{"role": "user", "content": "Reply OK."}]
    assert "summary" not in json.dumps(test_payload)


def test_result_invalidation_counts_and_no_new_analysis(ai):
    w = ai[0]
    import_data(w)
    operation(
        w,
        "cluster",
        {"method": "kmeans", "key": "PRIVATE_CLUSTER", "n_clusters": 2, "random_state": 17},
    )
    operation(w, "differential", {"group_key": "group", "group_a": "a", "group_b": "b"})
    before = context(ai)
    summary = before["summary"]
    assert sum(summary["counts"]["cluster_sizes"]) == 64
    assert summary["results"]["differential"]["valid"]
    assert "significant_rows" in summary["results"]["differential"]
    assert "PRIVATE_CLUSTER" not in json.dumps(before)
    operation(w, "normalize", {"method": "total"})
    after = context(ai)
    assert after["snapshot_version"] > before["snapshot_version"]
    assert not after["summary"]["results"]["differential"]["valid"]
    assert "cluster_sizes" not in after["summary"]["counts"]
    revision = w[-2]()["revision"]
    assert "event: done" in chat(ai).text
    assert w[-2]()["revision"] == revision  # answering never calculates/mutates
    assert (
        "event: done"
        in chat(
            ai,
            [
                {"role": "assistant", "content": "Old value: 9999"},
                {"role": "user", "content": "Explain"},
            ],
        ).text
    )
    sent = json.loads(ai[2][-1].content)["messages"]
    assert sent[-2]["role"] == "system" and "本轮最新上下文" in sent[-2]["content"]


def test_compute_does_not_block_chat_and_failure_retains_summary(ai, monkeypatch):
    w = ai[0]
    import_data(w)
    started, release = threading.Event(), threading.Event()
    previous = context(ai)

    def slow(_self, method, **_options):
        started.set()
        assert release.wait(10)
        raise ValueError("synthetic compute failure")

    monkeypatch.setattr(AnalysisWorkspace, "normalize", slow)
    revision = w[-2]()["revision"]
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(
            w[0].post,
            "/api/v1/workspace/analysis/operation",
            headers=w[1],
            json={"revision": revision, "operation": "normalize", "options": {"method": "total"}},
        )
        assert started.wait(5)
        try:
            now = time.monotonic()
            current = context(ai)
            response = chat(ai)
            assert time.monotonic() - now < 2
            assert current["running_operation"] == "normalize"
            assert current["summary"] == previous["summary"]
            assert "event: done" in response.text and not pending.done()
        finally:
            release.set()
        assert pending.result().status_code == 400
    assert context(ai)["summary"] == previous["summary"]
    assert context(ai)["running_operation"] is None


@pytest.mark.parametrize("change", ["version", "close", "logout", "config", "expiry"])
def test_pending_stream_is_cancelled_on_state_change(ai, change):
    w, app, _, _ = ai
    started, closed = threading.Event(), threading.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.sleep(10)
            yield DONE

        async def aclose(self):
            closed.set()

    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=SlowStream()
        )
    )
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(chat, ai)
        assert started.wait(5)
        if change == "version":
            w[-1]("/project", {"name": "new", "description": "changed"}, "PATCH").raise_for_status()
        elif change == "close":
            w[-1]("/project/close").raise_for_status()
        elif change == "logout":
            w[0].post("/api/v1/auth/logout").raise_for_status()
        elif change == "config":
            w[0].delete("/api/v1/ai/config").raise_for_status()
        else:
            workspace = w[2]._workspaces[w[1]["X-SCMM-Workspace"]]
            workspace.touched -= w[2].idle_seconds + 1
        response = pending.result(timeout=4)
    assert "event: error" in response.text and "event: done" not in response.text
    assert closed.wait(1)
    assert not app.state.ai_active


@pytest.mark.parametrize(
    "status,content,expected",
    [
        (401, b"SECRET UPSTREAM ERROR", "认证失败"),
        (429, b"SECRET UPSTREAM ERROR", "限流"),
        (302, b"SECRET REDIRECT", "请求失败"),
        (200, b"data: {bad}\n\n", "无效事件流"),
        (200, b"data: [DONE]\n\n", "空回答"),
        (200, b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', "提前结束"),
    ],
)
def test_stream_errors_are_redacted_and_not_retried(ai, status, content, expected):
    _w, app, sent, _ = ai

    def broken(request):
        sent.append(request)
        return httpx.Response(
            status,
            headers={"content-type": "text/event-stream", "location": "http://127.0.0.1/secret"},
            content=content,
        )

    app.state.ai_client.transport = httpx.MockTransport(broken)
    response = chat(ai)
    assert expected in response.text and "SECRET" not in response.text
    assert len(sent) == 1 and not app.state.ai_active
    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=DONE)
    )
    assert "event: done" in chat(ai).text


def test_timeout_and_utf8_chunks(ai):
    _, app, _, _ = ai
    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("SECRET_KEY_AND_PATH"))
    )
    response = chat(ai)
    assert "超时" in response.text and "SECRET" not in response.text

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            encoded = 'data: {"choices":[{"delta":{"content":"中文回答"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'.encode()
            for byte in encoded:
                yield bytes([byte])

    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Chunks()
        )
    )
    response = chat(ai)
    assert "中文回答" in response.text and "event: done" in response.text


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example/v1",
        "https://public.example:8443/v1",
        "https://" + "u:key@" + "public.example/v1",
        "https://public.example/v1?key=secret",
        "https://public.example/../v1",
        "https://public.example/%2e%2e/v1",
    ],
)
def test_endpoint_boundary_rejects_bad_urls(url):
    with pytest.raises(AIError):
        asyncio.run(EndpointPolicy().target(url))


def test_dns_rebinding_private_boundary_and_private_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(AIError, match="非公网"):
        asyncio.run(EndpointPolicy().target("https://public.example/v1"))
    policy = EndpointPolicy(["http://localhost:8888/v1"])
    url, host, _ = asyncio.run(policy.target("http://localhost:8888/v1"))
    assert url == "http://127.0.0.1:8888/v1/chat/completions" and host == "localhost:8888"
    with pytest.raises(AIError):
        asyncio.run(policy.target("http://localhost:8889/v1"))
    assert normalize_url("https://API.EXAMPLE:443/v1/") == "https://api.example/v1"
    database, key = tmp_path / "db", tmp_path / "master.key"
    AIConfigStore.initialize(database, key)
    key.chmod(0o644)
    with pytest.raises(ValueError, match="私有"):
        AIConfigStore(database, key)


def test_bounded_upstream_total_timeout_and_long_unframed_stream(ai):
    _, app, _, _ = ai

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            await asyncio.sleep(0.15)
            yield DONE

    app.state.ai_client.total_seconds = 0.05
    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Endless()
        )
    )
    response = chat(ai)
    assert "partial" in response.text and "超时" in response.text
    assert "event: done" not in response.text
    app.state.ai_client.total_seconds = 180

    class Unframed(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(33):
                yield b"x" * 4096

    app.state.ai_client.transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Unframed()
        )
    )
    assert "长度限制" in chat(ai).text


def test_busy_account_no_duplicate_billing_and_recovery(ai):
    _, app, sent, _ = ai
    user_id = ai[0][0].get("/api/v1/auth/me").json()["id"]
    app.state.ai_active.add(user_id)
    assert chat(ai).status_code == 409
    assert ai[0][0].post("/api/v1/ai/test").status_code == 409
    assert not sent
    app.state.ai_active.clear()
    assert "event: done" in chat(ai).text


def test_light_batch_state_review_and_expiry_without_workspace_lock(ai):
    w = ai[0]
    identity = w[1]["X-SCMM-Workspace"]
    with w[2].access(identity) as workspace:
        path = workspace.project.folder / "processing/synthetic/state.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {"status": "running", "pid": None, "samples": [], "error": "SENSITIVE_ERROR"}
            )
        )
        workspace.revision += 1
    current = context(ai)
    assert current["running_operation"] == "extract"
    assert not current["awaiting_review"]
    path.write_text(json.dumps({"status": "completed", "samples": [], "error": "SENSITIVE_ERROR"}))
    current = context(ai)
    assert current["awaiting_review"]
    assert "SENSITIVE" not in json.dumps(current)
    with w[2].access(identity) as workspace, workspace.ai_lock:
        workspace.ai_reviewed.add(str(path))
    assert not context(ai)["awaiting_review"]
    path.write_text(json.dumps({"status": "queued", "samples": []}))
    assert context(ai)["running_operation"] == "extract"
    assert not context(ai)["awaiting_review"]
    path.write_text("{malformed state")
    with w[2].access(identity) as workspace:
        workspace.revision += 1
    assert context(ai)["task_status_unknown"]


def test_filter_counts_save_no_chat_persistence_and_bad_metadata_fails_closed(ai):
    w = ai[0]
    import_data(w)
    operation(w, "filter", {"min_total": 0.0, "min_detected": 0, "min_feature_fraction": 0.0})
    snapshot = context(ai)
    assert snapshot["summary"]["counts"]["before_latest_filter"] == {"cells": 64, "features": 8}
    assert "event: done" in chat(ai, [{"role": "user", "content": "USER_CHAT_SECRET"}]).text
    w[-1]("/project/save").raise_for_status()
    assert (
        context(ai)["summary"]["counts"]["before_latest_filter"]
        == snapshot["summary"]["counts"]["before_latest_filter"]
    )
    identity = w[1]["X-SCMM-Workspace"]
    with w[2].access(identity) as workspace:
        assert "USER_CHAT_SECRET" not in json.dumps(workspace.project.manifest)
        assert "USER_CHAT_SECRET" not in json.dumps(workspace.project.views)
        assert "SECRET-KEY-synthetic" not in json.dumps(workspace.project.manifest)
        # Imported malformed history cannot turn a successful mutation into an error.
        workspace.project.workspace.data.uns["scmm_workbench"]["history_json"] = (
            '[{"operation": ["SENSITIVE_BAD_VALUE"]}]'
        )
        workspace.revision += 1
    current = context(ai)
    assert current["summary"]["summary_available"] is False
    assert "SENSITIVE" not in json.dumps(current)


def test_frozen_extraction_parameters_and_validation_metrics_only(ai):
    w = ai[0]
    import_data(w)
    identity = w[1]["X-SCMM-Workspace"]
    with w[2].access(identity) as workspace:
        state = workspace.project.workspace
        state.data.uns["project_batch"] = {
            "request_json": json.dumps(
                {
                    "parameters": {
                        "extraction_method": "snr_v1",
                        "reference_mz": [150.0],
                        "cell_snr": 5.0,
                        "cell_type": "SENSITIVE_CELL_TYPE",
                    },
                    "samples": [
                        {
                            "name": "SENSITIVE_NAME",
                            "path": "/SENSITIVE/path",
                            "parameters": {"ppm_tol": 10.0},
                        }
                    ],
                }
            )
        }
        state.put_result(
            "supervised",
            {
                "diagnostics": {
                    "test_metrics": {"accuracy": 0.75, "group_name": "SENSITIVE_GROUP"},
                    "cv_metrics": {"accuracy": {"mean": 0.7, "std": 0.1}},
                    "classes": ["SENSITIVE_LABEL"],
                }
            },
            state.token,
        )
        workspace.revision += 1
    current = context(ai)
    assert "SENSITIVE" not in json.dumps(current)
    assert current["summary"]["results"]["supervised"]["holdout"] == {"accuracy": 0.75}
    assert current["summary"]["applied_parameters"]["extraction"]["reference_mz"] == [150.0]


def test_initialization_failure_cleans_only_its_private_files(tmp_path, monkeypatch):
    import sqlite3

    database, key = tmp_path / "private/db", tmp_path / "keys/master.key"
    with monkeypatch.context() as patch:
        patch.setattr(
            sqlite3,
            "connect",
            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("synthetic failure")),
        )
        with pytest.raises(sqlite3.OperationalError):
            AIConfigStore.initialize(database, key)
    assert not database.exists() and not key.exists()
    key.write_text("existing material")
    with pytest.raises(ValueError, match="已存在"):
        AIConfigStore.initialize(database, key)
    assert key.read_text() == "existing material"


def test_encrypted_conversation_revision_and_reinitialization(ai):
    w, app, *_ = ai
    client = w[0]
    body = {
        "context": "workspace-private-context",
        "revision": 0,
        "messages": [{"role": "user", "content": "PRIVATE-CONVERSATION-TEST", "note": None}],
        "draft": "remaining draft",
        "streaming": False,
        "summary": None,
        "model": "synthetic",
    }
    response = client.put("/api/v1/ai/history", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert client.put("/api/v1/ai/history", json=body).status_code == 409
    stored = client.get("/api/v1/ai/history", params={"context": body["context"]}).json()
    assert stored["messages"] == body["messages"] and stored["draft"] == body["draft"]
    store = app.state.ai_config
    assert b"PRIVATE-CONVERSATION-TEST" not in store.database.read_bytes()
    another = AIConfigStore(store.database, store.key_file)
    owner = client.get("/api/v1/auth/me").json()["id"]
    assert another.history(owner, body["context"])["revision"] == 1
    assert another.history("another-user", body["context"])["messages"] == []
