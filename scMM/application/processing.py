"""Validated processing requests and server-side output boundaries."""

from __future__ import annotations

import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from scMM.file.io import validate_ms_file

from .storage import StorageCatalog

ProcessingPreset = Literal["balanced", "sensitive", "strict"]


@dataclass(frozen=True)
class ProcessingParameters:
    """Scientific and resource parameters accepted by the guided workflow."""

    ref_mz: float
    ppm_tol: float = 10.0
    resolution: float = 35_000.0
    resample_points_per_fwhm: float = 5.0
    ms_peak_snr_threshold: float = 10.0
    cell_snr: float = 5.0
    peak_snr: float = 3.0
    baseline_filter_size: int = 50
    max_zero_frac: float = 0.9
    n_jobs: int = 1
    mz_min: float = 100.0
    mz_max: float = 1000.0
    extraction_method: str = "legacy"
    reference_mz: tuple[float, ...] = ()
    reference_mode: str = "union"
    reference_ppm_tol: float = 10.0
    feature_snr_threshold: float = 3.0
    noise_window: int = 51
    feature_block_size: int = 256

    def __post_init__(self) -> None:
        from scMM.file._dataset_loading import validate_mz_range

        if not math.isfinite(self.ref_mz) or self.ref_mz <= 0:
            raise ValueError("ref_mz must be a positive finite number")
        validate_mz_range((self.mz_min, self.mz_max), self.ref_mz)
        if self.extraction_method not in {"legacy", "snr_v1"}:
            raise ValueError("extraction_method must be legacy or snr_v1")
        if self.reference_mode not in {"union", "intersection"}:
            raise ValueError("reference_mode must be union or intersection")
        if self.reference_mz and self.extraction_method != "snr_v1":
            raise ValueError("multiple references require snr_v1")
        for reference in self.reference_mz:
            if not math.isfinite(reference):
                raise ValueError("reference masses must be finite")
            validate_mz_range((self.mz_min, self.mz_max), reference)
        for key in ("noise_window", "feature_block_size", "baseline_filter_size", "n_jobs"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
        if self.noise_window < 2 or self.feature_block_size < 1:
            raise ValueError("noise_window >= 2 and feature_block_size >= 1 required")
        positive = {
            "ref_mz": self.ref_mz,
            "ppm_tol": self.ppm_tol,
            "resolution": self.resolution,
            "resample_points_per_fwhm": self.resample_points_per_fwhm,
            "ms_peak_snr_threshold": self.ms_peak_snr_threshold,
            "cell_snr": self.cell_snr,
            "peak_snr": self.peak_snr,
            "reference_ppm_tol": self.reference_ppm_tol,
            "feature_snr_threshold": self.feature_snr_threshold,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.baseline_filter_size < 1:
            raise ValueError("baseline_filter_size must be at least 1")
        if not math.isfinite(self.max_zero_frac) or not 0 <= self.max_zero_frac <= 1:
            raise ValueError("max_zero_frac must be between 0 and 1")
        if self.n_jobs == 0 or self.n_jobs < -1:
            raise ValueError("n_jobs must be -1 or a positive integer")

    @classmethod
    def from_preset(cls, preset: ProcessingPreset, ref_mz: float, **overrides: Any):
        """Build documented starting parameters with explicit user overrides."""
        presets: dict[str, dict[str, float]] = {
            "balanced": {},
            "sensitive": {
                "ms_peak_snr_threshold": 5.0,
                "cell_snr": 3.0,
                "peak_snr": 2.0,
                "max_zero_frac": 0.95,
            },
            "strict": {
                "ms_peak_snr_threshold": 15.0,
                "cell_snr": 8.0,
                "peak_snr": 5.0,
                "max_zero_frac": 0.8,
            },
        }
        try:
            values = {**presets[preset], **overrides}
        except KeyError as exc:
            raise ValueError(f"Unknown processing preset: {preset}") from exc
        return cls(ref_mz=ref_mz, **values)

    def load_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments consumed by ``CyESIData.load_from_file``."""
        values = asdict(self)
        values.pop("ref_mz")
        values["mz_range"] = (values.pop("mz_min"), values.pop("mz_max"))
        values["reference_mz"] = values["reference_mz"] or None
        return values


@dataclass(frozen=True)
class OutputRoot:
    """A named server directory in which processing results may be created."""

    label: str
    path: Path

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label:
            raise ValueError("Output root label cannot be empty")
        path = Path(self.path).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise NotADirectoryError(path)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "path", path)


class OutputCatalog:
    """Resolve output paths without allowing escape from configured roots."""

    def __init__(self, roots: tuple[OutputRoot, ...]) -> None:
        self._roots = {root.label: root for root in roots}
        if not self._roots:
            raise ValueError("At least one output root is required")
        if len(self._roots) != len(roots):
            raise ValueError("Duplicate output root label")

    @property
    def roots(self) -> tuple[OutputRoot, ...]:
        """Return configured roots in display order."""
        return tuple(self._roots.values())

    def root(self, label: str) -> OutputRoot:
        """Look up an output root by display label."""
        try:
            return self._roots[label]
        except KeyError as exc:
            raise KeyError(f"Unknown output root: {label}") from exc

    def resolve_target(self, label: str, name: str) -> Path:
        """Resolve one direct result directory below an output root."""
        safe_name = Path(name).name
        if safe_name != name or safe_name in {"", ".", ".."} or safe_name.startswith("."):
            raise ValueError(f"Invalid result name: {name!r}")
        root = self.root(label)
        target = root.path / safe_name
        parent = target.parent.resolve(strict=True)
        if parent != root.path:
            raise PermissionError(f"Output path is outside root {label!r}: {target}")
        if target.is_symlink():
            raise PermissionError(f"Result path cannot be a symbolic link: {target}")
        if target.exists() and target.resolve(strict=True).parent != root.path:
            raise PermissionError(f"Output path is outside root {label!r}: {target}")
        return target


@dataclass(frozen=True)
class ProcessingRequest:
    """One immutable request submitted by a browser session."""

    storage_label: str
    input_path: str
    output_label: str
    parameters: ProcessingParameters
    output_path: str | None = None
    result_name: str | None = None
    overwrite: bool = False
    defer_save: bool = False


@dataclass(frozen=True)
class ProcessingPlan:
    """Resolved paths and capacity information returned by preflight."""

    input_path: Path
    output_root: Path
    result_path: Path
    input_size_bytes: int
    free_bytes: int
    warnings: tuple[str, ...]


class ProcessingPlanner:
    """Validate a request before any expensive computation is started."""

    def __init__(self, storage: StorageCatalog, outputs: OutputCatalog) -> None:
        self.storage = storage
        self.outputs = outputs

    def preflight(self, request: ProcessingRequest) -> ProcessingPlan:
        """Resolve request boundaries and report non-fatal capacity warnings."""
        source = self.storage.resolve_raw_file(request.storage_label, request.input_path)
        validate_ms_file(source)
        result_name = request.result_name or source.stem
        if request.defer_save:
            output_root = self.outputs.root(request.output_label).path
            target = _resolve_target(output_root, result_name, request.output_label)
        elif request.output_path is None:
            output_root = self.outputs.root(request.output_label).path
            target = self.outputs.resolve_target(request.output_label, result_name)
        else:
            output_root = self.storage.resolve_output_directory(
                request.output_label, request.output_path
            )
            target = _resolve_target(output_root, result_name, request.output_label)
        if not request.defer_save and target.exists() and not request.overwrite:
            raise FileExistsError(f"Result already exists: {target}")

        disk_usage_path = output_root if output_root.exists() else output_root.parent
        free_bytes = shutil.disk_usage(disk_usage_path).free
        input_size = source.stat().st_size
        warnings: list[str] = []
        if not request.defer_save and request.overwrite and target.exists():
            warnings.append("Existing standard result files will be overwritten")
        if free_bytes < max(input_size * 3, 1_000_000_000):
            warnings.append("Output storage has less than the recommended free space")
        if request.parameters.n_jobs == -1:
            warnings.append("All available CPU cores will be used")

        return ProcessingPlan(
            input_path=source,
            output_root=output_root,
            result_path=target,
            input_size_bytes=input_size,
            free_bytes=free_bytes,
            warnings=tuple(warnings),
        )


def _resolve_target(output_root: Path, name: str, label: str) -> Path:
    safe_name = Path(name).name
    if safe_name != name or safe_name in {"", ".", ".."} or safe_name.startswith("."):
        raise ValueError(f"Invalid result name: {name!r}")
    target = output_root / safe_name
    if target.is_symlink():
        raise PermissionError(f"Result path cannot be a symbolic link: {target}")
    if target.exists() and target.resolve(strict=True).parent != output_root:
        raise PermissionError(f"Output path is outside root {label!r}: {target}")
    return target


__all__ = [
    "OutputCatalog",
    "OutputRoot",
    "ProcessingParameters",
    "ProcessingPlan",
    "ProcessingPlanner",
    "ProcessingPreset",
    "ProcessingRequest",
]
