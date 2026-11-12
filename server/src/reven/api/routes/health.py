"""结构化健康检查（#177）：db 失败 503 驱动 LB/哨兵；dsh/runner 降级保持 200 并显式标注。

- db：SELECT 1 实测（带超时）；失败即 503，容器编排/LB 据此摘流，杜绝"静态 200 误判部署成功"；
- dsh：运行时启动失败/未就绪标 degraded——保持 200 不触发重启风暴，供监控抓字段告警；
- background_runner：主循环任务死亡标 degraded；未挂载（start_background_tasks=False 等）标 disabled。

响应形态：``{"service": "reven", "status": "ok|degraded|fail", "checks": {"db", "dsh", "background_runner"}}``；
各检查项 status ∈ ok / degraded / disabled / fail（fail 仅 db）。
"""

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


def _check_dsh(request: Request) -> dict[str, str]:
    """dsh 运行时：未配置为 disabled；已配置但启动失败/未拉起为 degraded。"""
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None or not runtime.configured:
        return {"status": "disabled"}
    return {"status": "ok"} if runtime.available else {"status": "degraded"}


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
        "dsh": _check_dsh(request),
        "background_runner": _check_background_runner(request),
    }
    if checks["db"]["status"] == "fail":
        status, status_code = "fail", 503
    elif any(check["status"] == "degraded" for check in checks.values()):
        status, status_code = "degraded", 200
    else:
        status, status_code = "ok", 200
    return JSONResponse({"service": "reven", "status": status, "checks": checks}, status_code=status_code)
