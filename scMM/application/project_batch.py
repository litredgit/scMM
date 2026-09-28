"""Persistent sequential project extraction with sample-local failure handling."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import numpy as np
import pyopenms as oms

from scMM.file._dataset_loading import DatasetState, _annotate_single_file_frames
from scMM.file._sequential import merge_objects
from scMM.file.data import CyESIData
from scMM.file.io import align_frame, extract_peaks, load_single_file, sum_spec, validate_ms_file
from scMM.util.peak import filter_spectrum

from .processing import ProcessingParameters
from .projects import child_path, project_lock, write_json
from .tasks import background_tasks_supported, utc_now

SHARED_FIELDS = (
    "mz_min",
    "mz_max",
    "ppm_tol",
    "resolution",
    "resample_points_per_fwhm",
    "ms_peak_snr_threshold",
)


def preflight(project, storage):
    project.validate_samples()
    if not project.samples:
        raise ValueError("Add at least one raw sample")
    if project.manifest["feature_strategy"] not in {"shared", "independent"}:
        raise ValueError("Unknown feature strategy")
    base = ProcessingParameters(**project.manifest["parameters"])
    samples = []
    for sample in project.samples:
        path = storage.resolve_raw_file(sample["storage"], sample["path"])
        validate_ms_file(path)
        params = ProcessingParameters(**(sample["parameters"] or asdict(base)))
        if project.manifest["feature_strategy"] == "shared" and any(
            getattr(base, key) != getattr(params, key) for key in SHARED_FIELDS
        ):
            raise ValueError(f"Shared feature parameters differ for {sample['name']}")
        samples.append({**sample, "path": str(path), "parameters": asdict(params)})
    return {
        "samples": samples,
        "parameters": asdict(base),
        "feature_strategy": project.manifest["feature_strategy"],
        "feature_merge_ppm": project.manifest.get("feature_merge_ppm", 10.0),
    }


def read_batch(path):
    path = Path(path)
    state = json.loads(path.read_text())
    if state["status"] in {"queued", "running"} and state.get("pid"):
        command = Path(f"/proc/{state['pid']}/cmdline")
        try:
            content = command.read_bytes()
            live = b"scMM.application.project_batch" in content and str(path).encode() in content
        except OSError:
            live = False
        if not live:
            # Read-only recovery: do not race a live writer with a state-file rewrite.
            state = {**state, "status": "interrupted", "message": "Worker no longer running"}
    return state


def batches(project):
    root = child_path(project.folder, "processing")
    paths = [
        p
        for p in root.glob("*/state.json")
        if p.resolve().is_relative_to(root) and not p.parent.is_symlink()
    ]
    return sorted(
        paths, key=lambda p: json.loads(p.read_text()).get("created_at", ""), reverse=True
    )


def submit(project, storage, *, retry_path=None):
    if not background_tasks_supported():
        raise RuntimeError("Project extraction currently requires Linux")
    request = preflight(project, storage)
    prior = None
    if retry_path is not None:
        retry_path = Path(retry_path).resolve(strict=True)
        if retry_path not in [p.resolve() for p in batches(project)]:
            raise ValueError("Retry batch does not belong to this project")
        prior = read_batch(retry_path)
        if prior["status"] in {"queued", "running"}:
            raise ValueError("Cannot retry an active batch")
        previous = json.loads(retry_path.with_name("request.json").read_text())

        def scientific_request(value):
            return {
                "feature_strategy": value["feature_strategy"],
                "parameters": value["parameters"],
                "feature_merge_ppm": value["feature_merge_ppm"],
                "samples": [
                    {k: v for k, v in sample.items() if k != "preview"}
                    for sample in value["samples"]
                ],
            }

        if json.dumps(scientific_request(previous), sort_keys=True) != json.dumps(
            scientific_request(request), sort_keys=True
        ):
            raise ValueError(
                "Retry requires unchanged sample metadata and parameters; start a new batch"
            )
    with project_lock(project.folder):
        if any(read_batch(path)["status"] in {"queued", "running"} for path in batches(project)):
            raise RuntimeError("This project already has an active extraction batch")
        folder = child_path(project.folder, f"processing/{uuid4().hex}")
        folder.mkdir()
        path = folder / "state.json"
        if prior is not None:
            request["initial_results"] = []
            for row in prior["samples"]:
                if row["status"] == "succeeded":
                    output = child_path(retry_path.parent, row["output"])
                    shutil.copy2(output, folder / output.name)
                    request["initial_results"].append(row)
            targets = retry_path.with_name("shared_features.npy")
            if targets.exists():
                shutil.copy2(targets, folder / "shared_features.npy")
                request["reuse_shared_features"] = True
        request["created_at"] = utc_now()
        write_json(folder / "request.json", request)
        write_json(
            path,
            {
                "status": "queued",
                "created_at": utc_now(),
                "pid": None,
                "message": "Waiting for worker",
                "samples": [],
            },
        )
        env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (source_root, env.get("PYTHONPATH"))))
        try:
            with (folder / "worker.log").open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "scMM.application.project_batch", "--state", str(path)],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=source_root,
                    env=env,
                    start_new_session=True,
                )
            # Worker owns state after release; persist PID before allowing it to proceed.
            state = json.loads(path.read_text())
            write_json(path, {**state, "pid": process.pid})
            (folder / "start.ready").touch()
            threading.Thread(
                target=process.wait, daemon=True, name="scmm-project-worker-reaper"
            ).start()
        except Exception as exc:
            write_json(path, {"status": "failed", "message": str(exc), "samples": []})
            raise
        return path


def stop_after_current(path):
    path = Path(path)
    if read_batch(path)["status"] not in {"queued", "running"}:
        raise ValueError("Batch is not running")
    (path.parent / "stop.requested").touch()


def run_batch(path):
    path = Path(path)
    request = json.loads((path.parent / "request.json").read_text())
    state = {
        "status": "running",
        "pid": os.getpid(),
        "created_at": request["created_at"],
        "message": "Preparing features",
        "samples": [
            {"id": sample["id"], "name": sample["name"], "status": "waiting"}
            for sample in request["samples"]
        ],
    }
    previous = {r["id"]: r for r in request.get("initial_results", [])}
    state["samples"] = [previous.get(row["id"], row) for row in state["samples"]]

    def report(message):
        state["message"] = message
        write_json(path, state)

    report("Preparing shared features")
    try:
        targets = None
        base = ProcessingParameters(**request["parameters"])
        if request.get("reuse_shared_features"):
            targets = np.load(path.parent / "shared_features.npy", allow_pickle=False)
        elif request["feature_strategy"] == "shared":
            grid, total = None, None
            for i, sample in enumerate(request["samples"]):
                if (path.parent / "stop.requested").exists():
                    state["status"] = "stopped"
                    report("Stopped before extraction")
                    return
                try:
                    exp, _ = load_single_file(sample["path"])
                    summed = sum_spec(
                        exp,
                        resolution_200=base.resolution,
                        points_per_fwhm=base.resample_points_per_fwhm,
                        mz_range=(base.mz_min, base.mz_max),
                    )
                    mz, intensity = summed.get_peaks()
                    if grid is None:
                        grid, total = mz.copy(), intensity.astype(float)
                    else:
                        total += np.interp(grid, mz, intensity, left=0.0, right=0.0)
                    del exp, summed
                except Exception as exc:
                    state["samples"][i].update(status="failed", error=str(exc))
                report(f"Shared spectrum {i + 1}/{len(request['samples'])}")
            if grid is None:
                raise ValueError("No valid samples for shared features")
            spectrum = oms.MSSpectrum()
            spectrum.set_peaks((grid, total))
            filtered = filter_spectrum(spectrum, snr_threshold=base.ms_peak_snr_threshold)
            targets, _ = extract_peaks(filtered, resolution_200=base.resolution)
            targets = targets[(targets >= base.mz_min) & (targets <= base.mz_max)]
            if not len(targets):
                raise ValueError("No shared features detected")
            np.save(path.parent / "shared_features.npy", targets)
        for i, sample in enumerate(request["samples"]):
            row = state["samples"][i]
            if row["status"] in {"failed", "succeeded"}:
                continue
            if (path.parent / "stop.requested").exists():
                state["status"] = "stopped"
                report("Stopped; completed samples retained")
                return
            row["status"] = "running"
            report(f"Extracting {sample['name']}")
            try:
                params = ProcessingParameters(**sample["parameters"])

                def progress(value, message, name=sample["name"]):
                    report(f"{name}: {value:.0%} {message}")

                if targets is None:
                    obj = CyESIData.load_from_file(
                        sample["path"],
                        params.ref_mz,
                        progress_callback=progress,
                        **params.load_kwargs(),
                    )
                else:
                    exp, meta = load_single_file(sample["path"])
                    frame, obs = align_frame(exp, targets, ppm=params.ppm_tol)
                    _annotate_single_file_frames(obs, meta)
                    meta.update(ref_mz=params.ref_mz, mz_range=[params.mz_min, params.mz_max])
                    kwargs = params.load_kwargs()
                    for key in (
                        "mz_range",
                        "ppm_tol",
                        "resolution",
                        "resample_points_per_fwhm",
                        "ms_peak_snr_threshold",
                    ):
                        kwargs.pop(key)
                    obj = CyESIData._from_raw_state(
                        DatasetState(frame, obs, meta, params.ref_mz),
                        {**kwargs, "progress_callback": progress},
                    )
                    del exp, frame, obs
                obj.file_meta.update(name=sample["name"], source_file=sample["path"])
                for key, value in {
                    "sample_id": sample["id"],
                    "sample": sample["name"],
                    "group": sample["group"],
                    "subject": sample["subject"],
                    "batch": sample["batch"],
                    "source_file": sample["path"],
                }.items():
                    obj.peak_meta[key] = value
                if not len(obj.data) or not len(obj.data.columns):
                    raise ValueError("No cells or features retained")
                output = path.parent / f"{sample['id']}.h5ad"
                obj.save_h5ad(output)
                row.update(
                    status="succeeded",
                    output=output.name,
                    cells=len(obj.data),
                    features=len(obj.data.columns),
                )
            except Exception as exc:
                traceback.print_exc()
                row.update(status="failed", error=str(exc))
            report(f"Finished {i + 1}/{len(request['samples'])}")
        state["status"] = "completed"
        report("Review sample outcomes before building the dataset")
    except Exception as exc:
        traceback.print_exc()
        state["status"] = "failed"
        report(str(exc))


def reviewed_dataset(path, selected_ids):
    path = Path(path)
    state = read_batch(path)
    if state["status"] in {"queued", "running"}:
        raise ValueError("Wait until processing stops before review")
    rows = {r["id"]: r for r in state["samples"] if r["status"] == "succeeded"}
    if (
        not selected_ids
        or len(set(selected_ids)) != len(selected_ids)
        or set(selected_ids) - rows.keys()
    ):
        raise ValueError("Select successful samples exactly once")
    objects = [
        CyESIData.read_h5ad(child_path(path.parent, rows[key]["output"])) for key in selected_ids
    ]
    request = json.loads((path.parent / "request.json").read_text())
    ppm = 0.0 if request["feature_strategy"] == "shared" else request["feature_merge_ppm"]
    result = merge_objects(CyESIData, objects, ppm).to_anndata()
    result.uns["project_batch"] = {
        "source": str(path),
        "included_samples": list(selected_ids),
        "request_json": json.dumps(request),
    }
    return result


if __name__ == "__main__":
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    state_path = Path(args.state)
    deadline = time.monotonic() + 30
    while not (state_path.parent / "start.ready").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Worker start gate timeout")
        time.sleep(0.05)
    run_batch(state_path)
