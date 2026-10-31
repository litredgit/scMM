"""Local imports obey authorized roots, strict tables and source identities."""

import pytest

from scMM.application.compound_database import load_compound_database, load_external_evidence
from scMM.application.storage import StorageCatalog, StorageRoot


def test_local_database_mapping_and_evidence(tmp_path):
    storage = StorageCatalog([StorageRoot("local", tmp_path)])
    (tmp_path / "db.csv").write_text("record_id,formula,name\nglucose,C6H12O6,Glucose\n")
    database = load_compound_database(storage, "local", "db.csv", namespace="local")
    assert database.records[0]["record_id"] == "glucose"
    assert database.source["sha256"]
    (tmp_path / "e.mgf").write_text("BEGIN IONS\n50 10\nEND IONS\n")
    evidence = load_external_evidence(storage, "local", "e.mgf")
    assert evidence[0]["kind"] == "bulk_msms"
    with pytest.raises(ValueError, match="budget"):
        load_compound_database(storage, "local", "db.csv", namespace="local", max_bytes=2)
    (tmp_path / "bad.csv").write_text("record_id,record_id\na,b\n")
    with pytest.raises(ValueError, match="unique"):
        load_compound_database(storage, "local", "bad.csv", namespace="local")
