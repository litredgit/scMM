import subprocess
import sys


def test_application_import_without_fcntl():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.modules['fcntl'] = None; "
                "from scMM.application.tasks import background_tasks_supported; "
                "from scMM.application.workbench import AnalysisWorkspace; "
                "assert not background_tasks_supported(); "
                "assert AnalysisWorkspace().data is None"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
