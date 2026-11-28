"""Connection settings shared by the on-disk service databases."""


def configure_connection(db):
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA synchronous=NORMAL")


def enable_wal(db):
    if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
        raise RuntimeError("SQLite database does not support WAL mode")
