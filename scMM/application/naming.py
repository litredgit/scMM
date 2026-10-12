"""Readable output names; stored timestamps remain UTC for interoperability."""

import re
from datetime import UTC, datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def beijing_time(value=None, *, compact=False):
    instant = datetime.now(UTC) if value is None else datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(BEIJING).strftime(
        "%Y%m%d-%H%M%S" if compact else "%Y-%m-%d %H:%M:%S 北京时间"
    )


def safe_name(value, *, fallback="project", limit=60):
    return re.sub(r"[^\w-]+", "_", str(value)).strip("_")[:limit] or fallback


def dataset_filename(name, *, timestamp=None, revision=0, batches=()):
    labels = list(dict.fromkeys(str(v).strip() for v in batches if str(v).strip()))
    batch = "_".join(safe_name(v, limit=20) for v in labels[:2])
    if len(labels) > 2:
        batch += f"_等{len(labels)}批次"
    parts = [safe_name(name), batch, beijing_time(timestamp, compact=True), f"r{revision:03d}"]
    return "_".join(p for p in parts if p) + ".h5ad"


def project_dataset_filename(project, *, timestamp=None, revision=None):
    return dataset_filename(
        project.manifest["name"],
        timestamp=timestamp,
        revision=project.manifest["revision"] if revision is None else revision,
        batches=(sample.get("batch", "") for sample in project.samples),
    )
