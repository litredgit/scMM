"""Resolve application services without global mutable project state."""
# ruff: noqa: RUF001

from fastapi import Header, HTTPException, Request


def service(request: Request):
    return request.app.state.workspaces


def workspace_id(x_scmm_workspace: str = Header(default="")) -> str:
    if not x_scmm_workspace:
        raise HTTPException(status_code=400, detail="缺少工作区标识，请重新打开页面。")
    return x_scmm_workspace
