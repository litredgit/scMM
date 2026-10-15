"""Declarative lipid ranking rules. Scores never remove mass candidates."""
# ruff: noqa: RUF001

import csv
import io
import json
import math
import re

LEVELS = {"CATEGORY": 1, "MAIN_CLASS": 2, "SUB_CLASS": 3, "LIPID_CLASS": 4}


def class_values(row, level):
    value = str(row.get(level, ""))
    values = {value.casefold()}
    values.update(s.casefold() for s in re.findall(r"\[([^\]]+)\]", value))
    identifier = str(row.get("LM_ID", ""))
    if identifier.startswith("LM") and level != "LIPID_CLASS":
        values.add(
            identifier[2 : {"CATEGORY": 4, "MAIN_CLASS": 6, "SUB_CLASS": 8}[level]].casefold()
        )
    if level == "LIPID_CLASS":
        abbreviation = str(row.get("ABBREVIATION", "")).strip()
        values.add(re.split(r"[\s(]", abbreviation, maxsplit=1)[0].casefold())
    return values - {"", "nan", "none"}


def validate_rules(value, adducts):
    if not isinstance(value, dict) or set(value) - {"schema_version", "name", "rules"}:
        raise ValueError("规则需要 schema_version、name 和 rules 字段。")
    if value.get("schema_version", 1) != 1:
        raise ValueError("不支持的评分规则版本。")
    name = value.get("name", "")
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError("规则名称需为不超过 200 字的文本。")
    items = value.get("rules", [])
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("rules 需为列表，最多 10000 项。")
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {
            "kind",
            "level",
            "value",
            "polarity",
            "adduct",
            "score",
        }:
            raise ValueError("评分规则包含未知字段。")
        row = {k: item.get(k, "") for k in ("kind", "level", "value", "polarity", "adduct")}
        if any(not isinstance(v, str) or len(v) > 1000 for v in row.values()):
            raise ValueError("规则字段必须是有效文本。")
        score = item.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
        ):
            raise ValueError("score 必须为有限数值。")
        if row["kind"] not in {"class", "adduct"}:
            raise ValueError("kind 仅支持 class 或 adduct。")
        if row["level"] and row["level"] not in LEVELS:
            raise ValueError("level 仅支持 CATEGORY、MAIN_CLASS、SUB_CLASS、LIPID_CLASS。")
        if bool(row["level"]) != bool(row["value"]):
            raise ValueError("类别 level 和 value 必须一起填写。")
        if row["kind"] == "class" and (not row["level"] or row["adduct"]):
            raise ValueError("类别规则需指定 level/value，不填写 adduct。")
        if row["polarity"] not in {"", "pos", "neg"}:
            raise ValueError("polarity 仅支持空值、pos、neg。")
        if row["kind"] == "adduct":
            if row["adduct"] not in adducts:
                raise ValueError(f"不支持的单电荷加合物：{row['adduct']}")
            if row["polarity"] and adducts[row["adduct"]]["polarity"] != row["polarity"]:
                raise ValueError("加合物与规则极性不一致。")
        key = tuple(v.casefold() for v in row.values())
        if key in seen:
            raise ValueError("存在重复的评分条件。")
        seen.add(key)
        result.append({**row, "score": float(score)})
    return {"schema_version": 1, "name": name.strip(), "rules": result}


def import_rules(content, format, adducts):
    if format == "json":
        try:
            value = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise ValueError("规则 JSON 格式不合法。") from exc
    elif format == "csv":
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        if not reader.fieldnames or set(reader.fieldnames) - {
            "kind",
            "level",
            "value",
            "polarity",
            "adduct",
            "score",
        }:
            raise ValueError("CSV 表头应为 kind,level,value,polarity,adduct,score。")
        rows = []
        for row in reader:
            try:
                row["score"] = float(row.get("score", ""))
            except (ValueError, TypeError) as exc:
                raise ValueError("CSV score 必须为有限数值。") from exc
            rows.append(row)
        value = {"rules": rows}
    else:
        raise ValueError("仅支持 JSON 或 CSV 规则。")
    return validate_rules(value, adducts)


def score_candidate(row, rules):
    scores, evidence = {"class": 0.0, "adduct": 0.0}, []
    for kind in scores:
        matching = []
        for rule in rules["rules"]:
            if rule["kind"] != kind or (rule["polarity"] and rule["polarity"] != row["polarity"]):
                continue
            if rule["level"] and rule["value"].casefold() not in class_values(row, rule["level"]):
                continue
            if kind == "adduct" and rule["adduct"] != row["adduct"]:
                continue
            matching.append(rule)
        if matching:
            # A more specific condition replaces its fallback; it is not counted twice.
            chosen = max(matching, key=lambda r: (LEVELS.get(r["level"], 0), bool(r["polarity"])))
            scores[kind] = chosen["score"]
            evidence.append(chosen)
    return {
        "class_score": scores["class"],
        "adduct_score": scores["adduct"],
        "rule_score": sum(scores.values()),
        "scored": bool(evidence),
        "score_evidence": json.dumps(evidence, ensure_ascii=False),
    }


def rank_candidates(rows, rules):
    for row in rows:
        error = row["abs_ppm_error"]
        row["ppm_band"] = 1 if error <= 2 else 2 if error <= 5 else 3
        row.update(score_candidate(row, rules))
    rows.sort(key=lambda r: (r["feature_id"], r["ppm_band"], -r["rule_score"], r["candidate_id"]))
    best = {}
    for row in rows:
        best.setdefault(row["feature_id"], (row["ppm_band"], row["rule_score"]))
        row["top_ranked"] = best[row["feature_id"]] == (row["ppm_band"], row["rule_score"])
    return rows
