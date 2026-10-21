"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

from dataclasses import asdict

import numpy as np
import pytest

from scMM.application import RawPreviewService
from scMM.application.preview_cache import reusable_preview, save_preview, signature
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import preflight, read_batch, run_batch
from scMM.application.projects import write_json
from tests.support.project import setup_project


def test_preview_cache_skips_extraction_and_rejects_changed_inputs(tmp_path, monkeypatch):
    project, catalog = setup_project(tmp_path)
    project.manifest["feature_strategy"] = "independent"
    sample = project.samples[0]
    params = ProcessingParameters(**project.manifest["parameters"])
    preview = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    before = signature(sample["path"], params)
    preview.cell_detection(params)
    artifact = save_preview(project, sample, preview, params, before)
    sample["preview"] = {"parameters": asdict(params), "artifact": artifact, "confirmed": True}
    request = preflight(project, catalog)
    resolved = request["samples"][0]
    assert reusable_preview(project.folder, resolved) is not None
    assert reusable_preview(project.folder, resolved, np.array([999.0])) is None
    resolved["group"] = "changed"
    assert reusable_preview(project.folder, resolved) is not None
    from scMM.file.data import CyESIData

    original = CyESIData.load_from_file

    def guarded(path, *args, **kwargs):
        assert str(path) != sample["path"], "cached sample must not be extracted again"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(CyESIData, "load_from_file", guarded)
    folder = project.folder / "processing" / "batch-test"
    folder.mkdir()
    request["created_at"] = "test"
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    result = read_batch(folder / "state.json")
    assert result["status"] == "completed"
    assert result["samples"][0]["reused_preview"]
    assert all(row["status"] == "succeeded" for row in result["samples"])
    changed = {**resolved, "parameters": {**resolved["parameters"], "cell_snr": 7.0}}
    assert reusable_preview(project.folder, changed) is None
    from pathlib import Path

    Path(sample["path"]).touch()
    assert reusable_preview(project.folder, resolved) is None


def test_shared_preview_reuses_exact_batch_features(tmp_path, monkeypatch):
    from scMM.application.preview_cache import prepare_shared_targets
    from scMM.application.projects import ProjectStore
    from scMM.file.data import CyESIData

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    targets = prepare_shared_targets(project, request)
    sample = project.samples[0]
    params = ProcessingParameters(**request["samples"][0]["parameters"])
    preview = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    before = signature(sample["path"], params)
    preview.cell_detection(params, targets=targets)
    expected = preview.last_dataset.data.copy()
    sample["preview"] = {
        "artifact": save_preview(project, sample, preview, params, before),
        "parameters": asdict(params),
    }
    store = ProjectStore(tmp_path)
    store.save(project)
    project = store.open(project.folder)
    original = __import__(
        "scMM.application.project_batch", fromlist=["load_single_file"]
    ).load_single_file

    def guard(path):
        assert str(path) != sample["path"], "shared spectrum and cells should both be reused"
        return original(path)

    monkeypatch.setattr("scMM.application.project_batch.load_single_file", guard)
    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "shared-batch"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    rows = read_batch(folder / "state.json")["samples"]
    assert all(row["status"] == "succeeded" for row in rows), rows
    assert rows[0]["reused_preview"]
    actual = CyESIData.read_h5ad(folder / rows[0]["output"])
    np.testing.assert_array_equal(actual.data.to_numpy(), expected.to_numpy())
    np.testing.assert_array_equal(actual.data.columns, expected.columns)


def make_preview(project, catalog):
    sample = project.samples[0]
    params = ProcessingParameters(**project.manifest["parameters"])
    service = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    before = signature(sample["path"], params)
    service.cell_detection(params)
    artifact = save_preview(project, sample, service, params, before)
    sample["preview"] = {"artifact": artifact, "parameters": asdict(params)}
    return service, params, before, preflight(project, catalog)["samples"][0]


def replace_input(path):
    """Replace with equal size/mtime: those two fields alone cannot detect this."""
    import os
    from pathlib import Path

    path = Path(path)
    previous = path.stat()
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes().replace(b"149.9", b"149.8"))
    os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns == previous.st_mtime_ns
    assert path.stat().st_ino != previous.st_ino


def test_equal_size_and_mtime_replacement_invalidates_both_caches(tmp_path):
    from scMM.application.preview_cache import cached_shared_targets, prepare_shared_targets

    project, catalog = setup_project(tmp_path)
    _, _, _, sample = make_preview(project, catalog)
    request = preflight(project, catalog)
    prepare_shared_targets(project, request)
    assert cached_shared_targets(project.folder, request) is not None
    replace_input(sample["path"])
    assert reusable_preview(project.folder, sample) is None
    assert cached_shared_targets(project.folder, request) is None


def test_relocated_copy_requires_new_cache_identity(tmp_path):
    import shutil
    from pathlib import Path

    from scMM.application.preview_cache import cached_shared_targets, prepare_shared_targets

    project, catalog = setup_project(tmp_path)
    _, _, _, sample = make_preview(project, catalog)
    request = preflight(project, catalog)
    prepare_shared_targets(project, request)
    relocated = tmp_path / "relocated.mzML"
    shutil.copy2(sample["path"], relocated)
    assert relocated.read_bytes() == Path(sample["path"]).read_bytes()
    sample["path"] = str(relocated)
    request["samples"][0]["path"] = str(relocated)
    assert reusable_preview(project.folder, sample) is None
    assert cached_shared_targets(project.folder, request) is None
    # A newly calculated artifact can be reused at the new location.
    project.samples[0]["path"] = str(relocated)
    _, _, _, updated = make_preview(project, catalog)
    assert reusable_preview(project.folder, updated) is not None
    prepare_shared_targets(project, request)
    assert cached_shared_targets(project.folder, request) is not None


@pytest.mark.parametrize("name", ["data.h5ad", "targets.npy", "traces.csv", "detection.json"])
@pytest.mark.parametrize("damage", ["replace", "delete"])
def test_incomplete_or_changed_preview_is_a_cache_miss(tmp_path, name, damage):
    project, catalog = setup_project(tmp_path)
    _, _, _, sample = make_preview(project, catalog)
    artifact = project.folder / sample["preview"]["artifact"] / name
    if damage == "replace":
        artifact.write_bytes(b"changed artifact")
    else:
        artifact.unlink()
    assert reusable_preview(project.folder, sample) is None


def test_input_change_while_writing_preview_does_not_publish_identity(tmp_path, monkeypatch):
    project, catalog = setup_project(tmp_path)
    preview, params, before, sample = make_preview(project, catalog)
    original = preview.last_dataset.save_h5ad

    def changed(path):
        original(path)
        replace_input(sample["path"])

    monkeypatch.setattr(preview.last_dataset, "save_h5ad", changed)
    with pytest.raises(ValueError, match="Input changed"):
        save_preview(project, sample, preview, params, before)
    folders = list((project.folder / "processing").glob("preview-*"))
    assert len(folders) == 2
    assert sum((folder / "identity.json").exists() for folder in folders) == 1
    assert reusable_preview(project.folder, sample) is None


def test_input_change_while_preparing_shared_targets_is_not_published(tmp_path, monkeypatch):
    import scMM.file.io as io
    from scMM.application.preview_cache import prepare_shared_targets

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    original = io.load_single_file

    def changed(path):
        result = original(path)
        if str(path) == request["samples"][0]["path"]:
            replace_input(path)
        return result

    monkeypatch.setattr(io, "load_single_file", changed)
    with pytest.raises(ValueError, match="Input changed"):
        prepare_shared_targets(project, request)
    assert not list((project.folder / "processing").glob("shared-*"))


@pytest.mark.parametrize("kind", ["preview", "shared"])
def test_input_change_during_cache_validation_is_a_miss(tmp_path, monkeypatch, kind):
    import scMM.application.preview_cache as cache

    project, catalog = setup_project(tmp_path)
    _, _, _, sample = make_preview(project, catalog)
    request = preflight(project, catalog)
    cache.prepare_shared_targets(project, request)
    original = cache.digest_file
    changed = False

    def digest(path):
        nonlocal changed
        value = original(path)
        if not changed:
            replace_input(sample["path"])
            changed = True
        return value

    monkeypatch.setattr(cache, "digest_file", digest)
    result = (
        cache.reusable_preview(project.folder, sample)
        if kind == "preview"
        else cache.cached_shared_targets(project.folder, request)
    )
    assert changed
    assert result is None


@pytest.mark.parametrize("metadata", [{"version": 2}, [], None, {"version": 3, "artifacts": None}])
def test_legacy_or_malformed_identity_is_a_cache_miss(tmp_path, metadata):
    project, catalog = setup_project(tmp_path)
    _, _, _, sample = make_preview(project, catalog)
    folder = project.folder / sample["preview"]["artifact"]
    write_json(folder / "identity.json", metadata)
    assert reusable_preview(project.folder, sample) is None


@pytest.mark.parametrize("damage", ["missing", "corrupt", "metadata"])
def test_shared_artifact_damage_is_recomputed(tmp_path, damage):
    from scMM.application.preview_cache import cached_shared_targets, prepare_shared_targets

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    expected = prepare_shared_targets(project, request)
    path = next((project.folder / "processing").glob("shared-*.npy"))
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"broken")
    else:
        path.with_suffix(".json").write_text("null", encoding="utf-8")
    assert cached_shared_targets(project.folder, request) is None
    np.testing.assert_array_equal(prepare_shared_targets(project, request), expected)
    np.testing.assert_array_equal(cached_shared_targets(project.folder, request), expected)
