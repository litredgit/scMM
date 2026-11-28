"""Export the actual web schema using a temporary, empty service configuration."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from scMM.api.app import create_app
from scMM.application.auth import AuthStore
from scMM.application.storage import StorageRoot


def main():
    with TemporaryDirectory(prefix="scmm-openapi-") as directory:
        root = Path(directory)
        raw, projects = root / "raw", root / "projects"
        raw.mkdir()
        projects.mkdir()
        auth, _ = AuthStore.initialize(root / "auth.sqlite3", "schema")
        app = create_app(
            [StorageRoot("RAW", raw)],
            project_root=projects,
            static_root=None,
            auth_store=auth,
            server_config=SimpleNamespace(cookie_name="schema", cookie_secure=False, origins=()),
        )
        print(json.dumps(app.openapi(), ensure_ascii=False, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
