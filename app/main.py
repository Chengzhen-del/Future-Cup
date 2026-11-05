"""智巡 InspectAgent · 云端服务入口

启动：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs   （给端侧同学的 mock 就在这）
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import auth, inspections, kb, tasks, ws
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("inspectagent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import rag, store
    store.init_db()
    n = rag.warmup()          # 只读语料，不联网，毫秒级
    log.info("服务启动 | env=%s mock=%s llm=%s vision=%s | 规范语料 %s 条",
             settings.APP_ENV, settings.mock_mode, settings.has_llm,
             settings.has_vision, n)
    if settings.mock_mode:
        log.warning("当前为 MOCK 模式：未配置大模型 Key，返回确定性假数据（仅供联调）")
    if settings.RAG_ENABLED:
        # 放后台线程：首次建索引要下载 embedding 模型，不能挡住启动
        log.info("RAG_ENABLED=1，后台构建向量索引（首次较慢）")
        asyncio.get_running_loop().run_in_executor(None, rag.build_index)
    yield


app = FastAPI(
    title="智巡 InspectAgent Cloud",
    version="0.2.0",
    description="面向园区/配电房智能巡检的 Agent 云端服务：视觉判读 + 台账比对 + 规范检索 + 自动定级建单。",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(inspections.router, prefix="/api/v1")
app.include_router(kb.router, prefix="/api/v1")
app.include_router(ws.router)


# 🟢 P0-3: 登录鉴权中间件（AUTH_ENABLED=1 时生效；登录/刷新与 OPTIONS 预检放行）
_AUTH_WHITELIST = {"/api/v1/auth/login", "/api/v1/auth/refresh"}


@app.middleware("http")
async def auth_middleware(request, call_next):
    if (settings.AUTH_ENABLED and request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
            and request.url.path not in _AUTH_WHITELIST):
        from app.services import store
        parts = request.headers.get("authorization", "").split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""
        info = store.verify_token(token) if token else None
        if not info:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={
                "detail": {"code": "UNAUTHORIZED",
                           "message": "未登录或 token 已失效"}})
        request.state.user = info
    return await call_next(request)


# 🟢 P3-1: Trace 查询端点（生产级 Agent 调试必备）
@app.get("/api/v1/traces")
def list_traces(deviceId: str | None = None, limit: int = 20):
    from app.services import store
    return {"traces": store.list_traces(device_id=deviceId, limit=limit)}


@app.get("/api/v1/traces/{trace_id}")
def get_trace(trace_id: int):
    from app.services import store
    t = store.get_trace(trace_id)
    if not t:
        from fastapi import HTTPException
        raise HTTPException(404, "trace not found")
    return t


# 🟢 数据归档 API
@app.post("/api/v1/admin/archive")
def run_archive(days: int = 90):
    """手动触发归档（把 N 天前的巡检移到 archived_inspections）。"""
    from app.services import store
    return store.archive_old_data(days)


@app.delete("/api/v1/admin/archive")
def run_cleanup(days_memories: int = 180, days_traces: int = 30):
    """清理过期记忆和 Trace（默认记忆 180 天/Trace 30 天）。"""
    from app.services import store
    mem = store.cleanup_expired_memories(days_memories)
    trc = store.cleanup_old_traces(days_traces)
    return {"memories_deleted": mem, "traces_deleted": trc}


@app.get("/api/v1/alerts")
def list_alerts(unresolved: bool = True, limit: int = 50):
    from app.services import store
    return {"alerts": store.list_alerts(unresolved_only=unresolved, limit=limit)}


@app.post("/api/v1/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    from app.services import store
    ok = store.resolve_alert(alert_id)
    return {"ok": ok}


# 🟢 Token 用量/成本统计
@app.get("/api/v1/stats/tokens")
def token_stats(days: int = 7):
    """最近 N 天 token 用量聚合：总量 / 按天 / 按调用方 / 按模型。"""
    from app.services import store
    return store.get_token_stats(days=days)


# 🟢 端侧同步 API（HarmonyOS 端侧本地数据库同步）
@app.get("/api/v1/sync/snapshot")
def sync_snapshot(deviceId: str | None = None, since: str | None = None):
    """批量同步：端侧 App 启动时拉一次全量快照，之后增量拉。"""
    from app.services import store
    from app.config import settings
    devices = [d.model_dump() for d in store.list_devices()]
    tasks = [t.model_dump() for t in store.list_tasks()]
    inspections = []
    workorders = []
    import sqlite3
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    if since:
        rows = conn.execute(
            "SELECT * FROM inspections WHERE capturedAt >= ? ORDER BY capturedAt DESC LIMIT 5000",
            (since,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM inspections ORDER BY capturedAt DESC LIMIT 5000").fetchall()
    inspections = [dict(r) for r in rows]

    if since:
        rows = conn.execute(
            "SELECT * FROM workorders WHERE createdAt >= ? ORDER BY createdAt DESC LIMIT 5000",
            (since,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workorders ORDER BY createdAt DESC LIMIT 5000").fetchall()
    workorders = [dict(r) for r in rows]
    conn.close()

    return {"devices": devices, "tasks": tasks, "inspections": inspections,
            "workorders": workorders, "syncAt": _now(), "since": since}


@app.post("/api/v1/sync/conflict")
def resolve_conflict(payload: dict):
    """冲突上报：端侧和云端同时改了同一条记录时，端侧上报让云端仲裁。

    payload: {"table": "inspections", "id": "IN-xxx", "device_version": "...",
              "cloud_version": "...", "device_changes": {...}}
    返回: {"resolved": true/false, "winner": "cloud"|"device", "final": {...}}
    """
    # 简化版：永远以云端为准（生产可加更复杂策略）
    return {"resolved": True, "winner": "cloud", "message": "默认云端优先"}


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 取回巡检现场图片（报告页展示用）
app.mount("/media", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="media")

# Web 测试台（打开 http://localhost:8000/ 即可使用）
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

@app.get("/", tags=["system"], summary="Web 测试台入口")
def web_index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/")


@app.get("/health", tags=["system"], summary="健康检查")
def health():
    return {"ok": True, "env": settings.APP_ENV, "mock": settings.mock_mode,
            "llm": settings.has_llm, "vision": settings.has_vision}
