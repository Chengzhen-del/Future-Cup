"""知识库（向量 RAG）管理：状态查询 + 后台重建索引。"""
import threading

from fastapi import APIRouter

from app.services import rag

router = APIRouter(tags=["kb"])


@router.get("/kb/stats", summary="知识库状态（索引/语料/模式）")
def kb_stats():
    return rag.stats()


@router.post("/kb/rebuild", summary="后台重建向量索引")
def kb_rebuild():
    expected = rag.warmup()  # 语料条数（预计索引条数）
    threading.Thread(target=rag.build_index, daemon=True).start()
    return {"started": True, "expected": expected,
            "message": "向量索引正在后台重建，稍后可用 /kb/stats 查看状态"}