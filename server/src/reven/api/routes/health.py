"""数据库故障返回 503；Agent、检查点与后台任务的降级均可观测。"""

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_DB_CHECK_TIMEOUT_SECONDS = 3.0


async def _check_db(request: Request) -> dict[str, str]:
    """实测数据库连通性；未装配 factory 或探测失败均为 fail（整体 503）。"""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return {"status": "fail"}
    try:
        async with factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("健康检查数据库探测失败（error_type=%s）", type(exc).__name__)
        return {"status": "fail"}
    return {"status": "ok"}


async def _check_agent(request: Request) -> dict[str, str]:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None:
        return {"status": "disabled"}
    try:
        config = await asyncio.wait_for(runtime.resolve_config(), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("健康检查模型配置读取失败（error_type=%s）", type(error).__name__)
        return {"status": "degraded"}
    if config is None:
        return {"status": "disabled"}
    return {"status": "ok"} if runtime.available else {"status": "degraded"}


async def _check_checkpointer(request: Request) -> dict[str, str]:
    runtime = getattr(request.app.state, "agent_runtime", None)
    checkpoints = getattr(runtime, "checkpoints", None)
    if checkpoints is None:
        return {"status": "disabled"}
    try:
        ready = await asyncio.wait_for(checkpoints.ready(), timeout=_DB_CHECK_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("健康检查检查点探测失败（error_type=%s）", type(error).__name__)
        ready = False
    return {"status": "ok" if ready else "degraded"}


def _check_background_runner(request: Request) -> dict[str, str]:
    """后台 runner：未挂载为 disabled；可内省时主循环任务死亡为 degraded。"""
    runner = getattr(request.app.state, "background_runner", None)
    if runner is None:
        return {"status": "disabled"}
    healthy = getattr(runner, "healthy", None)
    if healthy is None:
        return {"status": "ok"}  # 注入的外部 runner 无可内省状态：在场即视为健康
    return {"status": "ok"} if healthy else {"status": "degraded"}


@router.get("/api/health")
async def health(request: Request) -> JSONResponse:
    checks = {
        "db": await _check_db(request),
        "agent": await _check_agent(request),
        "checkpointer": await _check_checkpointer(request),
        "background_runner": _check_background_runner(request),
    }
    if checks["db"]["status"] == "fail":
        status, status_code = "fail", 503
    elif any(check["status"] == "degraded" for check in checks.values()):
        status, status_code = "degraded", 200
    else:
        status, status_code = "ok", 200
    return JSONResponse({"service": "reven", "status": status, "checks": checks}, status_code=status_code)
