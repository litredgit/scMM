"""Account endpoints; authentication and role checks live at the common boundary."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

router = APIRouter(prefix="/api/v1", tags=["authentication"])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(StrictBody):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class Password(StrictBody):
    current_password: SecretStr = Field(default=SecretStr(""), max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


class CreateAccount(StrictBody):
    username: str = Field(min_length=3, max_length=64)
    role: str = "member"


class UpdateAccount(StrictBody):
    active: bool | None = None
    reset_password: bool = False


def public_user(principal):
    return {k: principal[k] for k in ("id", "username", "role", "must_change", "csrf")}


def clear_cookie(response, request):
    config = request.app.state.server_config
    response.delete_cookie(
        config.cookie_name, httponly=True, secure=config.cookie_secure, samesite="lax"
    )


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    store, config = request.app.state.auth, request.app.state.server_config
    token, principal = store.login(
        body.username,
        body.password.get_secret_value(),
        request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        config.cookie_name,
        token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=store.absolute_seconds,
        path="/",
    )
    return public_user(principal)


@router.get("/auth/me")
def me(request: Request):
    return public_user(request.state.principal)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    request.app.state.auth.logout(request.state.principal)
    clear_cookie(response, request)
    return {"ok": True}


@router.post("/auth/password")
def password(body: Password, request: Request, response: Response):
    request.app.state.auth.change_password(
        request.state.principal,
        body.current_password.get_secret_value(),
        body.new_password.get_secret_value(),
    )
    clear_cookie(response, request)
    return {"ok": True}


@router.get("/admin/users")
def users(request: Request):
    return request.app.state.auth.users()


@router.post("/admin/users", status_code=201)
def create_user(body: CreateAccount, request: Request):
    return request.app.state.auth.create_user(
        body.username, body.role, by=request.state.principal["id"]
    )


@router.patch("/admin/users/{identity}")
def update_user(identity: str, body: UpdateAccount, request: Request):
    return request.app.state.auth.update_user(
        identity, active=body.active, reset=body.reset_password, by=request.state.principal["id"]
    )


@router.get("/admin/audit")
def audit(request: Request):
    return request.app.state.auth.audit_log()
