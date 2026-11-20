"""Conservative species labels for display, backed by Goslin."""

import re
from functools import lru_cache
from threading import Lock

_CLASSES = frozenset(
    [
        "PC",
        "PE",
        "PS",
        "PI",
        "PG",
        "PA",
        "PGP",
        "PIP",
        "PIP2",
        "PIP3",
        "LPC",
        "LPE",
        "LPS",
        "LPI",
        "LPG",
        "LPA",
        "CL",
        "MLCL",
        "DLCL",
        "BMP",
        "LBPA",
        "MG",
        "DG",
        "TG",
        "MGDG",
        "DGDG",
        "SQDG",
        "SQMG",
        "DGTS",
        "DGTA",
        "LDGTS",
        "LDGTA",
        "Cer",
        "CerP",
        "CerPE",
        "SM",
        "SPB",
        "SPBP",
        "HexCer",
        "Hex2Cer",
        "SE",
        "ST",
    ]
)
_INPUT_CLASSES = _CLASSES | {"CE", "GlcCer", "GalCer", "ManCer", "LacCer", "MGD"}
_PARSER_LOCK = Lock()


@lru_cache(maxsize=1)
def _parser():
    from pygoslin.parser.Parser import LipidParser

    return LipidParser()


@lru_cache(maxsize=32768)
def _standard_species(name):
    from pygoslin.domain.LipidExceptions import LipidException
    from pygoslin.domain.LipidLevel import LipidLevel

    value = re.sub(r"\s*\(LM[A-Z]{2}\d+\)\s*$", "", name)
    head = re.split(r"[\s(]", value, maxsplit=1)[0]
    if len(value) > 200 or (head not in _INPUT_CLASSES and value != "Cholesterol"):
        return None
    value = re.sub(r"^MGD(?=[ (])", "MGDG", value)
    value = re.sub(r"^(PIP[23]?)\([^:)]*\)\s*\(", r"\1(", value)
    value = re.sub(r"\b([dmt])\s+(?=\d+:)", r"\1", value)
    isotopes = ""
    try:
        with _PARSER_LOCK:
            parsed = _parser().parse(value)
        label = parsed.lipid.get_lipid_string(LipidLevel.SPECIES)
        if parsed.adduct:
            isotopes = parsed.adduct.get_heavy_isotope_string()
    except LipidException:
        betaine = re.fullmatch(r"(L?DGT[SA])\s*\(?((?:\d+:\d+)(?:[/_]\d+:\d+)*)\)?", value)
        if not betaine:
            return None
        chains = [tuple(map(int, p.split(":"))) for p in re.split(r"[/_]", betaine[2])]
        label = f"{betaine[1]} {sum(c for c, _ in chains)}:{sum(d for _, d in chains)}"
    head, _, composition = label.partition(" ")
    head = {"GlcCer": "HexCer", "GalCer": "HexCer", "ManCer": "HexCer", "LacCer": "Hex2Cer"}.get(
        head, head
    )
    if head not in _CLASSES or not composition or (head == "ST" and value != "Cholesterol"):
        return None
    if head == "SE":
        pair = re.fullmatch(r"(\d+):(\d+)[/_](\d+):(\d+)", composition)
        if pair:
            c1, d1, c2, d2 = map(int, pair.groups())
            composition = f"{c1 + c2}:{d1 + d2}"
    return f"{head}({composition})" + (f"[M{isotopes}]" if isotopes else "")


def species_label(name):
    name = str(name).strip()
    return _standard_species(name) or name


def record_species(record):
    values = [
        str(record[key])
        for key in ("ABBREVIATION", "COMMON_NAME", "NAME", "name")
        if record.get(key)
    ]
    for value in values:
        label = _standard_species(value.strip())
        if label is not None:
            # Some libraries carry fixed-isotope labels only in the formula field.
            if "[M[" not in label:
                formula = str(record.get("FORMULA") or record.get("formula") or "")
                isotopes = []
                for a, e, b, f, count in re.findall(
                    r"(?:\[(\d+)([A-Z][a-z]?)\]|\((\d+)\)([A-Z][a-z]?))(\d*)", formula
                ):
                    isotopes.append(f"[{a or b}]{e or f}{count if count != '1' else ''}")
                for element, count in re.findall(r"([DT])(?![a-z])(\d*)", formula):
                    isotopes.append(
                        f"[{'2' if element == 'D' else '3'}]H{count if count != '1' else ''}"
                    )
                if isotopes:
                    label += "[M" + "".join(sorted(isotopes)) + "]"
            return label
    return str(record.get("COMMON_NAME") or record.get("name") or (values[0] if values else ""))
