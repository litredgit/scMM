"""Administrator-only observations and narrowly scoped public document leases."""
# ruff: noqa: RUF001

import time
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from scMM.application.auth import AuthError

router = APIRouter(prefix="/api/v1", tags=["monitor"])
Route = Literal[
    "/projects",
    "/samples",
    "/raw",
    "/extraction",
    "/preprocess",
    "/analysis",
    "/results",
    "/parameters",
    "/account",
    "/admin/monitor",
    "/login",
]


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9-]{32,36}$")
    route: Route
    visibility: Literal["visible", "hidden", "suspended"]
    workspace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Heartbeat(Page):
    token: SecretStr = Field(min_length=20, max_length=128)
    closed: bool = False


class Registration(Page):
    registration_secret: SecretStr | None = Field(default=None, min_length=32, max_length=128)
    closed: bool = False


def user(request):
    try:
        return request.app.state.auth.authenticate(
            request.cookies.get(request.app.state.server_config.cookie_name, "")
        )
    except AuthError:
        return None


@router.post("/presence/register")
async def register(body: Registration, request: Request):
    service = request.app.state.monitor
    # Source budget is bounded, without persisting addresses in monitoring records.
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    budgets = service.registration_budget
    count, start = budgets.get(key, (0, now))
    if now - start > 60:
        count, start = 0, now
    if count >= 120 or (len(budgets) >= 4096 and key not in budgets):
        raise AuthError("页面登记过于频繁，请稍后重试。", 429, "presence_rate_limit")
    budgets[key] = count + 1, start
    principal = user(request)
    return service.store.register(
        body.id,
        service.instance,
        principal["id"] if principal else None,
        body.route,
        body.visibility,
        body.workspace_id,
        registration_secret=body.registration_secret.get_secret_value()
        if body.registration_secret
        else None,
        closed=body.closed,
    )


@router.post("/presence/heartbeat")
async def heartbeat(body: Heartbeat, request: Request):
    service = request.app.state.monitor
    principal = user(request)
    return service.store.heartbeat(
        body.id,
        body.token.get_secret_value(),
        service.instance,
        principal["id"] if principal else None,
        body.route,
        body.visibility,
        body.workspace_id,
        body.closed,
    )


@router.get("/admin/monitor")
async def monitor(request: Request):
    return request.app.state.monitor.snapshot()


@router.get("/admin/monitor/history")
async def history(request: Request):
    return {
        "interval_seconds": 60,
        "retention_hours": 24,
        "points": request.app.state.monitor.store.history(),
    }


@router.get("/admin/monitor/events")
def events(
    request: Request,
    username: str = "",
    action: str = "",
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
):
    with request.app.state.auth.connect() as db:
        where = "audit.at>=? AND (?='' OR users.username=?) AND (?='' OR action=?)"
        params = (time.time() - 86400, username, username, action, action)
        rows = db.execute(
            f"""SELECT audit.at,users.username,action,resource,status FROM audit
            LEFT JOIN users ON users.id=audit.user_id WHERE {where} ORDER BY audit.id DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        counts = db.execute(
            """SELECT action,COUNT(*) AS count FROM audit WHERE at>=? GROUP BY action""",
            (time.time() - 86400,),
        ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "counts_24h": [dict(r) for r in counts],
        "offset": offset,
    }
