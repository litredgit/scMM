"""Install a synthetic plugin as an independent distribution in a temporary directory."""


def install_method_package(target):
    target.mkdir()
    metadata = target / "scmm_method_fixture-1.2.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: scmm-method-fixture\nVersion: 1.2.0\n")
    (metadata / "entry_points.txt").write_text(
        "[scmm.methods.v1]\nfixture-methods = scmm_fixture_methods:plugin\n"
    )
    (target / "scmm_fixture_methods.py").write_text(SOURCE, encoding="utf-8")
    return target


SOURCE = """\
import numpy as np
import pandas as pd

from scMM.plugins import AnnotationCandidate, CellEvent, Method, Parameter, Plugin, StatisticalReport


def detect(inputs, options):
    frame = int(inputs.signal.sum(axis=1).to_numpy().argmax())
    return [CellEvent(frame, frame, frame)]


def quantify(inputs, options):
    result = inputs.scans.signal.iloc[[event.apex for event in inputs.events]].reset_index(drop=True)
    return result * options["scale"]


def annotation(inputs, options):
    row = inputs.features.iloc[0]
    return [AnnotationCandidate(str(row.name), "Fixture candidate", float(row["mz"]))]


def scale(inputs, options):
    if options["scale"] == 0:
        return inputs.values[:-1]
    return inputs.values * options["scale"]


def project(inputs, options):
    return inputs.values[:, :2]


def cluster(inputs, options):
    return np.where(inputs.values[:, 0] > np.median(inputs.values[:, 0]), 0, 1)


def statistic(inputs, options):
    values = inputs.values[:, 0]
    table = pd.DataFrame({"cell_id": inputs.observation_ids, "value": values,
                          "group": inputs.observations[options["column"]].to_numpy()})
    figure = {"data": [{"type": "scatter", "x": list(range(len(values))), "y": values.tolist()}],
              "layout": {"xaxis": {"title": "Observation"}, "yaxis": {"title": "Intensity"}}}
    return StatisticalReport(table, figure)


factor = Parameter("scale", "倍率", "number", default=2.0, minimum=0, maximum=10)
plugin = Plugin((
    Method("detect", "Fixture detector", "cell_detection", detect),
    Method("quantify", "Fixture quantifier", "cell_extraction", quantify, (factor,), "Synthetic apex intensity"),
    Method("annotate", "Fixture annotation", "annotation", annotation),
    Method("scale", "Fixture scale", "preprocessing", scale, (factor,)),
    Method("project", "Fixture embedding", "reduction", project),
    Method("cluster", "Fixture clusters", "clustering", cluster),
    Method("report", "Fixture statistics", "statistics", statistic,
           (Parameter("column", "分组列", "observation"),)),
))
"""
