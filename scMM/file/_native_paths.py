"""Check native path encoding before handing XML filenames to OpenMS."""
# ruff: noqa: RUF001

import sys
from pathlib import Path


def process_ansi_codepage():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.kernel32.GetACP()


def require_openms_path_encoding(path: Path) -> None:
    """Do not misreport a known Windows encoding mismatch as corrupt XML."""
    if not str(path.absolute()).isascii() and process_ansi_codepage() not in (None, 65001):
        raise RuntimeError(
            "当前 Windows Python 进程未启用原生 UTF-8，OpenMS 无法可靠读写中文路径。"
            "请用 scripts/scmm_windows.py prepare/run 建立源码运行环境，"
            "或使用已配置进程级 UTF-8 的 scMM 打包解释器；无需修改系统区域设置。"
        )
