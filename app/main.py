"""智巡 InspectAgent · 云端服务入口

启动：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs   （给端侧同学的 mock 就在这）
"""
import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.security import require_role

from app import errors
from app.config import settings
from app.routers import auth, inspections, kb, ops, sync, tasks, ws
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("inspectagent")


async def _cleanup_loop() -> None:
    """v8：定时清理（记忆 / Trace / 已归档媒体），间隔 CLEANUP_INTERVAL_HOURS，0=关闭。"""
    from app.services import store
    interval = settings.CLEANUP_INTERVAL_HOURS * 3600
    if interval <= 0:
        log.info("定时清理已关闭（CLEANUP_INTERVAL_HOURS=0）")
        return
    while True:
        await asyncio.sleep(interval)
        try:
            res = await asyncio.to_thread(store.run_cleanup_job)
            log.info("定时清理完成: %s", res)
        except Exception as e:  # noqa: BLE001
            log.warning("定时清理失败: %s", e)


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
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(
    title="智巡 InspectAgent Cloud",
    version="0.2.0",
    description="面向园区/配电房智能巡检的 Agent 云端服务：视觉判读 + 台账比对 + 规范检索 + 自动定级建单。",
    lifespan=lifespan,
)

# 中间件顺序（后注册 = 更外层）：CORS > 鉴权 > traceId > 路由异常处理
errors.install(app)


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
            return errors.fail(request, 401, "未登录或 token 已失效", "UNAUTHORIZED")
        request.state.user = info
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(inspections.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(ops.router, prefix="/api/v1")
app.include_router(kb.router, prefix="/api/v1")
app.include_router(ws.router)


# 🟢 数据归档 API（低频运维，保留在 main 里）
@app.post("/api/v1/admin/archive")
def run_archive(days: int = 90, _user=Depends(require_role("admin"))):
    """手动触发归档（把 N 天前的巡检移到 archived_inspections），仅 admin。"""
    from app.services import store
    return store.archive_old_data(days)


@app.delete("/api/v1/admin/archive")
def run_cleanup(days_memories: int = 180, days_traces: int = 30,
                days_media: int | None = None, _user=Depends(require_role("admin"))):
    """清理过期记忆 / Trace / 已归档媒体的物理文件，仅 admin。"""
    from app.services import store
    return {
        "memories_deleted": store.cleanup_expired_memories(days_memories),
        "traces_deleted": store.cleanup_old_traces(days_traces),
        "media": store.cleanup_old_media(days_media or settings.MEDIA_RETENTION_DAYS),
    }


# v8：/media 改为鉴权端点（原 StaticFiles 无法校验 token）。
# 端侧 Image 组件不能带 Header，因此同时支持 ?token=xxx。
_MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(jpg|jpeg|png|webp|gif|bmp|wav|mp3|m4a|mp4)$")


@app.get("/media/{filename}", tags=["media"], summary="巡检现场图片/音频（需 token）")
def get_media(filename: str, request: Request):
    if not _MEDIA_NAME_RE.match(filename):
        return errors.fail(request, 404, "媒体文件不存在", "NOT_FOUND")
    path = settings.UPLOAD_DIR / filename
    if not path.is_file():
        return errors.fail(request, 404, "媒体文件不存在", "NOT_FOUND")
    if settings.AUTH_ENABLED:
        from app.services import store
        parts = request.headers.get("authorization", "").split()
        token = (parts[1] if len(parts) == 2 and parts[0].lower() == "bearer"
                 else request.query_params.get("token", ""))
        if not store.verify_token(token):
            return errors.fail(request, 401, "访问媒体文件需要有效 token", "UNAUTHORIZED")
    return FileResponse(path)

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
