"""统一错误响应（P1-8）：所有异常都返回同一结构，端侧只解析一种格式。

{
  "code":    "TASK_NOT_FOUND",   // 机器可读，端侧用它做分支
  "message": "任务不存在",        // 人可读
  "detail":  "",                 // 可选补充
  "traceId": "a1b2c3d4"          // 与服务端日志、X-Trace-Id 响应头一致
}
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("inspectagent")

# 状态码 -> 默认 code（端侧可按 code 做界面提示）
CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _trace_id(request: Request) -> str:
    tid = getattr(request.state, "traceId", "")
    if not tid:
        tid = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
        request.state.traceId = tid
    return tid


def error_body(code: str, message: str, detail: str = "", trace_id: str = "") -> dict:
    return {"code": code, "message": message, "detail": detail, "traceId": trace_id}


def fail(request: Request, status_code: int, message: str,
         code: str = "", detail: str = "") -> JSONResponse:
    """在中间件里直接返回统一错误（请求还没进路由时用）。"""
    tid = _trace_id(request)
    return JSONResponse(
        status_code=status_code,
        content=error_body(code or CODE_BY_STATUS.get(status_code, "ERROR"),
                           message, detail, tid),
        headers={"X-Trace-Id": tid},
    )


def install(app: FastAPI) -> None:
    """注册 traceId 中间件与三类异常处理器（需在其它中间件之前调用）。"""

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        tid = _trace_id(request)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        d = exc.detail
        code = CODE_BY_STATUS.get(exc.status_code, "ERROR")
        if isinstance(d, dict):
            code = d.get("code") or code
            message = str(d.get("message") or d.get("detail") or code)
            detail = str(d.get("detail") or "").replace(str(d.get("message") or ""), "", 1).strip()
        else:
            message, detail = str(d), ""
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message, detail, _trace_id(request)),
            headers={"X-Trace-Id": _trace_id(request)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors()[:6]:
            loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_ERROR", "请求参数校验失败",
                               "; ".join(parts), _trace_id(request)),
            headers={"X-Trace-Id": _trace_id(request)},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        tid = _trace_id(request)
        log.exception("[traceId=%s] 未捕获异常 %s %s", tid, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "服务端内部错误，请凭 traceId 查日志",
                               str(exc)[:200], tid),
            headers={"X-Trace-Id": tid},
        )
