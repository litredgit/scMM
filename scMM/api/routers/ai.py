"""Authenticated personal settings and ephemeral, read-only streaming chat."""

# ruff: noqa: RUF001
import asyncio
import json
from contextlib import suppress
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from scMM.application.ai_client import normalize_url
from scMM.application.ai_config import AIError
from scMM.application.ai_summary import SYSTEM_PROMPT, encode_event

from ..dependencies import workspace_id

router = APIRouter(prefix="/api/v1/ai", tags=["AI assistant"])
Page = Literal[
    "projects",
    "samples",
    "raw",
    "extraction",
    "preprocess",
    "analysis",
    "results",
    "parameters",
    "account",
]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class Chat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Page
    messages: list[Message] = Field(min_length=1, max_length=24)


def store(request):
    value = request.app.state.ai_config
    if value is None:
        raise AIError("服务器尚未启用个人 AI 配置，请联系管理员。", 503, "ai_unavailable")
    return value


@router.get("/config")
def configuration(request: Request):
    if request.app.state.ai_config is None:
        return {"available": False, "configured": False, "base_url": "", "model": ""}
    return store(request).public(request.state.principal["id"])


@router.put("/config")
async def save(body: Settings, request: Request):
    value = store(request)
    base = normalize_url(body.base_url)
    if any(ord(c) < 32 for c in body.model):
        raise AIError("Model 不能含控制字符。")
    # Validate the endpoint without sending a key. Saving is atomic for all fields.
    await request.app.state.ai_client.policy.target(base)
    return value.save(
        request.state.principal["id"], base, body.model, body.api_key.get_secret_value()
    )


@router.delete("/config")
def delete(request: Request):
    store(request).delete(request.state.principal["id"])
    return {"ok": True}


@router.get("/context")
def context(request: Request, page: Page, identity: str = Depends(workspace_id)):
    return request.app.state.workspaces.ai_context(identity, request.state.principal["id"], page)


def configured(request):
    value = store(request).load(request.state.principal["id"])
    if value is None:
        raise AIError("请先在“我的账号”配置个人 AI API。", 400, "ai_not_configured")
    return value


def session_check(request):
    request.app.state.auth.authenticate(
        request.cookies.get(request.app.state.server_config.cookie_name, "")
    )


@router.post("/test")
async def test_connection(request: Request):
    config = configured(request)
    if request.state.principal["id"] in request.app.state.ai_active:
        raise AIError("已有 AI 请求进行中，请先停止。", 409)
    request.app.state.ai_active.add(request.state.principal["id"])
    stream = request.app.state.ai_client.stream(config, [{"role": "user", "content": "Reply OK."}])
    try:
        # Minimum test, no workspace or experimental context. Close after first text.
        async with asyncio.timeout(40):
            await anext(stream)
        session_check(request)
        return {"ok": True, "model": config["model"]}
    except TimeoutError:
        raise AIError("AI 连接测试超时，请手动重试。", 504) from None
    finally:
        await stream.aclose()
        request.app.state.ai_active.discard(request.state.principal["id"])


@router.post("/chat")
async def chat(body: Chat, request: Request, identity: str = Depends(workspace_id)):
    if body.messages[-1].role != "user" or sum(len(m.content) for m in body.messages) > 48000:
        raise AIError("请以用户问题结束对话；对话过长时请清空后重试。")
    config = configured(request)
    user_id = request.state.principal["id"]
    if user_id in request.app.state.ai_active:
        raise AIError("已有 AI 请求进行中，请先停止。", 409)
    manager = request.app.state.workspaces
    snapshot = manager.ai_context(identity, user_id, body.page)
    history = [m.model_dump() for m in body.messages]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history[:-1],
        {
            "role": "system",
            "content": "本轮最新上下文：" + json.dumps(snapshot, ensure_ascii=False),
        },
        history[-1],
    ]

    def check_current():
        session_check(request)
        latest = manager.ai_context(identity, user_id, body.page)
        if latest["snapshot_version"] != snapshot["snapshot_version"] or any(
            latest[k] != snapshot[k]
            for k in ("running_operation", "awaiting_review", "task_status_unknown")
        ):
            raise AIError("项目或数据版本已改变，本回答依据已过期，请重新提问。", 409, "ai_stale")
        if store(request).load(user_id) != config:
            raise AIError("个人 API 配置已改变，请重新提问。", 409, "ai_stale")

    async def events():
        from scMM.application.auth import AuthError

        upstream, pending = None, None
        # Streaming begins after response headers; reserve here with no await.
        if user_id in request.app.state.ai_active:
            yield encode_event(
                "error", {"message": "已有 AI 请求进行中，请先停止。", "code": "ai_busy"}
            )
            return
        request.app.state.ai_active.add(user_id)
        try:
            await asyncio.to_thread(check_current)
            yield encode_event("context", {"model": config["model"], "context": snapshot})
            upstream = request.app.state.ai_client.stream(config, messages)
            while True:
                pending = asyncio.create_task(anext(upstream))
                while True:
                    ready, _ = await asyncio.wait({pending}, timeout=0.5)
                    await asyncio.to_thread(check_current)
                    if ready:
                        break
                    yield ": keepalive\n\n"
                try:
                    delta = pending.result()
                except StopAsyncIteration:
                    yield encode_event("done", {"ok": True})
                    return
                yield encode_event("delta", {"text": delta})
        except AuthError:
            yield encode_event(
                "error", {"message": "登录已失效，本次回答已停止。", "code": "session_changed"}
            )
        except AIError as exc:
            yield encode_event("error", {"message": str(exc), "code": exc.code})
        finally:
            if pending and not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration, AIError):
                    await pending
            if upstream:
                await upstream.aclose()
            request.app.state.ai_active.discard(user_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
