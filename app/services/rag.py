"""巡检规范检索（RAG）。

- 有 chromadb 就走向量检索：EMBEDDING_MODEL 非空用 OpenAI 兼容 /embeddings，为空用
  Chroma 内置默认 embedding（all-MiniLM-L6-v2 ONNX，无需 key）
- 装不上 chromadb / 建索引失败 / 检索失败，一律退化为关键词匹配（绝不卡住）
语料放 knowledge/rules.md，按 "## 设备名" 分组，每条 "- " 列表项抽取
{id, device_type, text, source}（source 来自【来源:xxx】）。
"""
import logging
import re
import threading
from pathlib import Path

from app.config import settings

log = logging.getLogger("inspectagent.rag")

# __file__ = app/services/rag.py → parents[2] 才是项目根目录
KNOWLEDGE_FILE = Path(__file__).resolve().parents[2] / "knowledge" / "rules.md"

# 只读内存语料，任何情况下都能检索，绝不依赖网络
_CORPUS: list[dict] = []

# 内置兜底语料：rules.md 缺失 / chroma 不可用时至少能检索出东西
FALLBACK_RULES = [
    {"id": "r1", "device_type": "低压配电柜",
     "text": "配电柜母线接头运行温度不得超过 70℃，超过 70℃ 判定为异常，需 24 小时内复检。",
     "source": "GB/T 14048.1"},
    {"id": "r2", "device_type": "低压配电柜",
     "text": "配电室环境温度应保持在 5℃~40℃，相对湿度不超过 80%RH，凝露需立即处理。",
     "source": "GB 50053"},
    {"id": "r3", "device_type": "高压柜",
     "text": "发现绝缘子破损、放电痕迹、异响、焦糊味，判定为紧急，需立即停电检修。",
     "source": "DL/T 596"},
    {"id": "r4", "device_type": "低压配电柜",
     "text": "仪表读数异常、指示灯熄灭、标识牌脱落，判定为关注，纳入下次巡检重点。",
     "source": "工厂变配电站运行规程"},
    {"id": "r5", "device_type": "消防器材",
     "text": "灭火器压力不足、安全工器具超期未检，判定为异常，7 日内整改闭环。",
     "source": "GB 50140"},
    {"id": "r6", "device_type": "电缆沟",
     "text": "电缆沟积水、封堵不严、有小动物活动痕迹，判定为关注，需做防水封堵。",
     "source": "GB 50168"},
]

COLLECTION_NAME = "inspect_rules"
MEMORY_COLLECTION = "inspection_memories"
_collection = None
_mem_collection = None
_collection_lock = threading.Lock()

_SOURCE_RE = re.compile(r"【来源[:：]\s*(.*?)】")


class _OpenAIEmbeddingFunction:
    """OpenAI 协议 /embeddings 的 Chroma embedding_function（key/base/model 全走 settings）。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
        self._model = model

    def __call__(self, input):  # noqa: A001 - Chroma 约定接口名就是 input
        resp = self._client.embeddings.create(model=self._model, input=list(input))
        return [d.embedding for d in resp.data]


def _make_embedding_function():
    """EMBEDDING_MODEL 非空 → 走 EMBEDDING_BASE_URL /embeddings；否则 Chroma 默认 ONNX。"""
    if settings.EMBEDDING_MODEL:
        return _OpenAIEmbeddingFunction(settings.EMBEDDING_API_KEY,
                                        settings.EMBEDDING_BASE_URL,
                                        settings.EMBEDDING_MODEL)
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        return DefaultEmbeddingFunction()
    except Exception as e:  # noqa: BLE001
        log.warning("默认 embedding 不可用: %s", e)
        return None


def _parse_rules() -> list[dict]:
    """解析 rules.md：按 '## ' 识别设备类型，'- ' 列表项抽取 text + 【来源:xxx】。"""
    if not KNOWLEDGE_FILE.exists():
        return [dict(r) for r in FALLBACK_RULES]
    raw = KNOWLEDGE_FILE.read_text(encoding="utf-8")
    device_type = ""
    entries: list[dict] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("## "):
            device_type = s[3:].strip()
            continue
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        if not body:
            continue
        m = _SOURCE_RE.search(body)
        source = m.group(1).strip() if m else ""
        text = _SOURCE_RE.sub("", body).strip()
        if not text:
            continue
        entries.append({"id": f"r{len(entries) + 1}",
                        "device_type": device_type,
                        "text": text,
                        "source": source})
    return entries or [dict(r) for r in FALLBACK_RULES]


def _load_entries(force: bool = False) -> list[dict]:
    """返回结构化语料；force=True 时重新读 rules.md（build_index 每次重建都重新读）。"""
    global _CORPUS
    if not _CORPUS or force:
        _CORPUS = _parse_rules()
    return _CORPUS


def warmup() -> int:
    """只读语料、不联网、不建索引。启动必调，耗时 <10ms。"""
    return len(_load_entries())


def _query_keys(query: str) -> list[str]:
    """连续中文串拆成整词 + 二元组，提升关键词回退时的命中率。"""
    keys: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fa5]{2,}", query):
        keys.append(run)
        if len(run) >= 3:
            keys.extend(run[i:i + 2] for i in range(len(run) - 1))
    return keys


def _keyword_search_entries(query: str, top_k: int, pool=None) -> list[dict]:
    """关键词检索，返回条目；pool 为 None 表示全量语料（可回退兜底），否则仅在 pool 内检索。"""
    filtered = pool is not None
    if pool is None:
        pool = _load_entries()
    keys = _query_keys(query)
    scored = []
    for i, e in enumerate(pool):
        t = e["text"]
        score = sum(1 for k in keys if k in t)
        if score:
            scored.append((score, -i, e))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    if scored:
        return [e for _, _, e in scored[:top_k]]
    if filtered:
        return []
    return [dict(r) for r in FALLBACK_RULES[:top_k]]


def _entry_by_text(pool: list[dict], text: str) -> dict | None:
    for e in pool:
        if e["text"] == text:
            return e
    return None


def build_index() -> int:
    """把 rules.md 灌进 Chroma，返回条目数。幂等（每次删除后重建，每次重新读 rules.md）。"""
    global _collection
    entries = _load_entries(force=True)  # 每次重建都重新读 rules.md，避免读一次缓存
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=str(settings.CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:  # noqa: BLE001
            pass

        ef = _make_embedding_function()
        kwargs = {}
        if ef is not None:
            kwargs["embedding_function"] = ef
        col = client.create_collection(COLLECTION_NAME, **kwargs)
        src = entries or [dict(r) for r in FALLBACK_RULES]
        col.add(
            ids=[e["id"] for e in src],
            documents=[e["text"] for e in src],
            metadatas=[{"device_type": e.get("device_type", ""),
                        "source": e.get("source", "")} for e in src],
        )
        _collection = col
        log.info("RAG 索引构建完成：%s 条（embedding=%s）", len(src),
                 settings.EMBEDDING_MODEL or "local-onnx")
        return len(src)
    except Exception as e:  # noqa: BLE001
        log.warning("Chroma 不可用，RAG 退化为关键词检索: %s", e)
        _collection = None
        try:
            from app.services import store
            store.log_alert("warn", "rag", "Chroma 向量检索不可用，已退化关键词兜底", str(e)[:200])
        except Exception:
            pass
        return 0


def _chroma_lock():
    """🔒 P0-3 Chroma 锁 - 所有 Chroma collection 操作必须用 with _chroma_lock(): 包裹。"""
    class _Ctx:
        def __enter__(self):
            _collection_lock.acquire()
        def __exit__(self, *a):
            _collection_lock.release()
    return _Ctx()


def rebuild() -> int:
    """重建向量索引，返回条目数（失败返回 0）。"""
    return build_index()


def search_ex(query: str, top_k: int = 3, device_type: str | None = None) -> tuple[list[dict], str]:
    """检索规范条目，返回 ([{text,source,device_type}, ...], mode)，mode ∈ {"vector","keyword"}。

    device_type 非空时先按设备类型过滤语料再检索。
    """
    entries = _load_entries()
    pool = [e for e in entries if e["device_type"] == device_type] if device_type else entries

    results: list[dict] = []
    mode = "keyword"
    if _collection is not None:
        try:
            qkwargs = {"query_texts": [query], "n_results": top_k}
            if device_type:
                qkwargs["where"] = {"device_type": device_type}
            with _chroma_lock():
                res = _collection.query(**qkwargs)
            docs = res.get("documents", [[]])[0] or []
            seen: set[str] = set()
            for d in docs:
                if d and d not in seen:
                    seen.add(d)
                    e = _entry_by_text(pool, d)
                    results.append(e if e else {
                        "text": d, "source": "", "device_type": device_type or ""})
            if results:
                mode = "vector"
        except Exception as e:  # noqa: BLE001
            log.warning("向量检索失败，退化关键词: %s", e)

    if not results:
        results = _keyword_search_entries(query, top_k, pool if device_type else None)
        mode = "keyword"

    return [{"text": e["text"], "source": e.get("source", ""),
             "device_type": e.get("device_type", "")} for e in results], mode


def search_cited(query: str, top_k: int = 3) -> list[dict]:
    """检索并带出处，返回 [{text,source,device_type}, ...]（不按设备类型过滤）。"""
    results, _ = search_ex(query, top_k)
    return results


def search(query: str, top_k: int = 3) -> list[str]:
    """检索相关规范条目文本（供 state_machine / tools 既有调用，签名与行为保持不变）。"""
    results, _ = search_ex(query, top_k)
    return [r["text"] for r in results]


def stats() -> dict:
    """索引与语料状态快照。"""
    return {
        "index_built": _collection is not None,
        "total": len(_load_entries()),
        "mode": "vector" if _collection is not None else "keyword",
        "chroma_dir": str(settings.CHROMA_DIR),
        "embedding_model": settings.EMBEDDING_MODEL or "local-onnx(default)",
    }

# ============= P1: 历史巡检记忆 RAG =============

def _get_mem_collection():
    """懒加载 inspection_memories collection（不可用则返回 None）。"""
    global _mem_collection
    if _mem_collection is not None:
        return _mem_collection
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(settings.CHROMA_DIR))
        try:
            col = client.get_or_create_collection(MEMORY_COLLECTION)
        except Exception:
            col = client.create_collection(MEMORY_COLLECTION)
        _mem_collection = col
        return col
    except Exception as e:  # noqa: BLE001
        log.warning("记忆 RAG 不可用（Chroma 没装好？）：%s", e)
        _mem_collection = None
        return None


def add_memory_to_index(mem_id: str, summary: str, device_id: str = "",
                        device_type: str = "", level: str = "", keywords: str = "") -> bool:
    """单条记忆入向量索引（巡检完成后异步调）。"""
    col = _get_mem_collection()
    if col is None:
        return False
    try:
        doc = f"[{device_type}] {level} - {summary} 关键词: {keywords}"
        with _chroma_lock():
            col.upsert(ids=[mem_id], documents=[doc],
                       metadatas=[{"device_id": device_id, "device_type": device_type,
                                   "level": level}])
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("记忆入索引失败: %s", e)
        return False


def build_memory_index() -> int:
    """全量历史记忆入 RAG（启动时或手动 rebuild）。"""
    from app.services import store
    col = _get_mem_collection()
    if col is None:
        return 0
    mems = store.load_all_memories(limit=200)
    if not mems:
        return 0
    ids, docs, mets = [], [], []
    for m in mems:
        ids.append("mem-" + str(m["id"]))
        docs.append(f"[{m.get('device_type','')}] {m.get('level','')} - {m.get('summary','')}")
        mets.append({"device_id": m.get("deviceId", ""),
                     "device_type": m.get("deviceType", ""),
                     "level": m.get("level", "")})
    try:
        with _chroma_lock():
            col.upsert(ids=ids, documents=docs, metadatas=mets)
        log.info("历史巡检记忆索引完成：%s 条", len(ids))
        return len(ids)
    except Exception as e:  # noqa: BLE001
        log.warning("记忆全量入索引失败: %s", e)
        return 0


def search_memory(query: str, device_id: str | None = None, top_k: int = 3) -> list[dict]:
    """检索相似的历史巡检记忆（跨设备/跨时间）。Chroma 不可用时退化为从 store 直接拉。"""
    # 先走 DB 按 device_id 过滤的精确命中（P0 已实现）
    from app.services import store
    db_hits = store.load_recent_memories(device_id, limit=top_k) if device_id else store.load_all_memories(limit=5)

    col = _get_mem_collection()
    if col is None:
        return db_hits[:top_k]

    try:
        qkwargs = {"query_texts": [query], "n_results": top_k}
        if device_id:
            qkwargs["where"] = {"device_id": device_id}
        with _chroma_lock():
            res = col.query(**qkwargs)
        docs = res.get("documents", [[]])[0] or []
        ids = res.get("ids", [[]])[0] or []
        seen_ids = {m["inspectionId"] for m in db_hits}
        for d, mid in zip(docs, ids):
            if mid in seen_ids:
                continue
            # docs 内容是我们自己拼的 "[设备类型] 级别 - 摘要"，解析回去
            db_hits.append({"inspectionId": mid.replace("mem-", ""), "summary": d,
                            "deviceId": device_id or "", "capturedAt": "",
                            "level": ""})
        return db_hits[:top_k]
    except Exception as e:  # noqa: BLE001
        log.warning("记忆向量检索失败，退回 DB: %s", e)
        return db_hits[:top_k]
