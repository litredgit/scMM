"""Recorded preprocessing caveats for supervised validation; no scientific inference."""
# ruff: noqa: RUF001

import json
from copy import deepcopy

from scMM.util.intensity import intensity_states


def preprocessing_audit(data, layer):
    """Describe recorded history without asserting that every step affects this layer."""
    warnings = [
        "细胞数不等于生物重复；所选分组列的不同值只代表分组单位，不能证明生物学独立。",
        "分组划分不能消除在全数据上插补、选特征等上游处理造成的泄漏。",
        "反复查看留出结果或据此调参后，该留出集不再是独立测试；本报告不追踪所有外部调参。",
    ]
    metadata = data.uns.get("scmm_workbench", {})
    try:
        history = json.loads(metadata.get("history_json", "[]"))
        if not isinstance(history, list) or any(
            not isinstance(step, dict) or not isinstance(step.get("operation"), str)
            for step in history
        ):
            raise ValueError("invalid history")
        steps = [
            {
                "operation": step.get("operation", "unknown"),
                "layer": step.get("layer", ""),
                "parameters": deepcopy(step.get("parameters", {})),
            }
            for step in history
        ]
    except (AttributeError, TypeError, ValueError):
        steps = []
        warnings.append("预处理历史无法解析；无法核实是否存在上游泄漏。")
    if not steps:
        warnings.append("没有可核实的预处理步骤记录，不代表原始数据或已排除泄漏。")
    risks = sorted(
        {
            step["operation"]
            for step in steps
            if step["operation"] in {"impute", "filter", "outliers"}
            or (
                step["operation"] == "normalize"
                and isinstance(step["parameters"], dict)
                and step["parameters"].get("method") in {"pqn", "quantile", "zscore", "minmax"}
            )
        }
    )
    if risks:
        warnings.append(
            "处理记录包含在监督划分前执行的插补、筛选或按全体数据拟合的变换；"
            "记录可能包含其他层或已恢复步骤，请核对所选输入。切换强度层不会恢复已筛除的轴。"
        )
    try:
        state = intensity_states(data).get(layer or "X", "unknown")
    except (AttributeError, TypeError, ValueError, KeyError):
        state = "unknown"
        warnings.append("强度来源无法核实，不据此推断上游处理范围。")
    return {
        "input_layer": layer or "X",
        "input_intensity_state": state,
        "recorded_steps": steps,
        "recorded_risk_operations": risks,
        "history_scope": "记录级提示，不将历史中的所有步骤断言为所选层的实际变换；不执行折内重预处理。",
        "warnings": warnings,
    }
