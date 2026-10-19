"""Stable display sorting; never modifies scientific scores or review records."""

import math


def sorted_rows(rows, key, descending=False):
    if key == "recommended":
        return list(rows)
    field = "ppm_error" if key == "abs_ppm_error" else key

    def value(row):
        item = row.get("sample_name", row.get(field)) if field == "sample" else row.get(field)
        if field == "rule_score" and not row.get("scored", True):
            return None
        if key == "abs_ppm_error" and item is not None:
            item = abs(item)
        return item.casefold() if isinstance(item, str) else item

    present, missing = [], []
    for row in rows:
        item = value(row)
        if item is None or (isinstance(item, float) and not math.isfinite(item)):
            missing.append(row)
        else:
            present.append(row)
    return sorted(present, key=value, reverse=descending) + missing
