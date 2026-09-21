from pathlib import Path

import numpy as np


def quality_metrics(data):
    """Return per-cell and per-file quality-control tables."""
    X = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    cell = data.obs.copy()
    cell["total_intensity"] = np.nansum(X, axis=1)
    cell["detected_features"] = np.count_nonzero(X > 0, axis=1)
    if "source_file" not in cell:
        cell["source_file"] = "unknown"

    numeric = [
        "total_intensity",
        "detected_features",
        *[name for name in cell.columns if name.startswith("reference_intensity_")],
    ]
    per_file = cell.groupby("source_file", observed=True)[numeric].agg(
        ["count", "mean", "median", "std", "min", "max"]
    )
    return {"cell": cell, "file": per_file}


def render_quality_report(data, output_file):
    """Create a compact PDF report of core CyESI quality distributions."""
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    metrics = quality_metrics(data)
    cell = metrics["cell"]
    target = Path(output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    reference_columns = [name for name in cell.columns if name.startswith("reference_intensity_")]

    with PdfPages(target) as pdf:
        fig = Figure(figsize=(11, 4))
        axes = fig.subplots(1, 2)
        for source, group in cell.groupby("source_file", observed=True):
            axes[0].hist(group["total_intensity"], bins=40, alpha=0.5, label=source)
            axes[1].hist(group["detected_features"], bins=40, alpha=0.5, label=source)
        axes[0].set_title("Total intensity per cell")
        axes[1].set_title("Detected features per cell")
        for ax in axes:
            ax.set_ylabel("Cells")
            ax.legend(fontsize=8)
        fig.tight_layout()
        pdf.savefig(fig)
        fig.clear()

        for column in reference_columns:
            fig = Figure(figsize=(7, 4))
            ax = fig.subplots()
            values = [
                group[column].dropna().to_numpy()
                for _, group in cell.groupby("source_file", observed=True)
            ]
            labels = [source for source, _ in cell.groupby("source_file", observed=True)]
            ax.boxplot(values, showfliers=False)
            ax.set_xticks(range(1, len(labels) + 1), labels)
            ax.set_title(column.replace("_", " "))
            ax.set_ylabel("Intensity")
            fig.tight_layout()
            pdf.savefig(fig)
            fig.clear()
    return target
