"""Conservative sum-composition display labels; never combine measured intensities."""

import re


def species_label(name):
    text = str(name).strip()
    match = re.match(r"^([A-Za-z][A-Za-z0-9-]*)\s*(?:\(|\s)(.+?)\)?$", text)
    if not match:
        return text
    lipid_class, chains = match.groups()
    pairs = re.findall(r"(?<![\d:])(\d+):(\d+)", chains)
    if not pairs:
        return text
    carbon = sum(int(c) for c, _ in pairs)
    bonds = sum(int(d) for _, d in pairs)
    # Preserve linkage and oxidation notation; formula remains part of the grouping key.
    linkage = "P-" if "P-" in chains else "O-" if "O-" in chains else ""
    suffix = ";" + chains.split(";", 1)[1].rstrip(")") if ";" in chains else ""
    return f"{lipid_class}({linkage}{carbon}:{bonds}{suffix})"


def record_species(record):
    return species_label(
        record.get("ABBREVIATION")
        or record.get("COMMON_NAME")
        or record.get("NAME")
        or record.get("name", "")
    )
