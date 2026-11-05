"""存储层：SQLite（stdlib sqlite3，不引 ORM）。

6 张表 + schema_version 迁移 + seed（6 台设备 / 6 条任务）。
初赛阶段够用；决赛换 PostgreSQL 只改这一个文件。

字段全链路 camelCase；DB 存 0/1 表示 bool；时间统一 "YYYY-MM-DD HH:mm:ss" 字符串。
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta

from app.config import settings
from app.schemas import (ConflictResp, Finding, InspectReq, InspectResp,
                         SyncInspection, SyncSnapshot, TaskItem,
                         DeviceProfile, WorkOrder)

# ---- 设备 / 任务 seed ----
# 列序：id, name, type, location, ratedTemp, ratedHumidity, installDate, lastInspectAt, history, qrCode
SEED_DEVICES = [
    ("D-3001", "3号低压配电柜", "低压配电柜", "A区配电房", 70.0, 80.0, "2023-05-20",
     "2026-09-20", "2026-08-12 接头温度 66℃（偏高）；2026-09-20 复测正常", ""),
    ("D-3002", "1号干式变压器", "干式变压器", "A区配电房", 100.0, 80.0, "2023-05-20",
     "2026-10-15", "2026-07-03 绕组温度 92℃；2026-10-15 正常", ""),
    ("D-3003", "A区电缆沟", "电缆沟", "A区配电房", None, None, "2023-06-01",
     "2026-09-15", "2026-06-20 有积水已清理；防火封堵完好", ""),
    ("D-3004", "直流屏", "直流屏", "B区配电房", 40.0, 80.0, "2023-08-11",
     "2026-09-01", "2026-09-01 单体电压 2.23V 正常", ""),
    ("D-3005", "2号高压柜", "高压柜", "C区配电房", 65.0, 80.0, "2023-08-11",
     "2026-05-11", "2026-05-11 局部放电检测未见异常", ""),
    ("D-3006", "灭火器组", "消防器材", "B区配电房", None, None, "2023-03-08",
     "2026-03-08", "2026-03-08 压力表正常，下次检验 2027-03", ""),
]

SEED_TASKS = [
    ("T-1001", "D-3001", "3号配电柜例行巡检", "3号低压配电柜", "A区配电房", "待巡检", "高", "2026-11-05", "运维班组A"),
    ("T-1002", "D-3002", "变压器温度复测", "1号干式变压器", "A区配电房", "待巡检", "高", "2026-11-05", "运维班组A"),
    ("T-1003", "D-3003", "电缆沟防水检查", "A区电缆沟", "A区配电房", "待巡检", "中", "2026-11-06", "运维班组A"),
    ("T-1004", "D-3006", "消防器材有效期核查", "灭火器组", "B区配电房", "进行中", "中", "2026-11-07", "运维班组A"),
    ("T-1005", "D-3004", "直流屏蓄电池巡检", "直流屏", "B区配电房", "待巡检", "低", "2026-11-08", "运维班组A"),
    ("T-1006", "D-3005", "高压柜局部放电检测", "2号高压柜", "C区配电房", "待巡检", "高", "2026-11-09", "运维班组A"),
]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(settings.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def paginate(items: list, page: int | None = None, page_size: int = 20):
    """P1-9 分页：不传 page 返回原列表（旧客户端零改动）；传了返回信封。"""
    if not page:
        return items
    page = max(1, int(page))
    ps = max(1, min(int(page_size or 20), 200))
    return {"items": items[(page - 1) * ps: page * ps],
            "total": len(items), "page": page, "pageSize": ps}


def absolute_media_url(path: str, base_url: str = "") -> str:
    """P1-10：把 /media/xxx 拼成完整可访问地址；已是 http 地址则原样返回。"""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    base = (base_url or settings.PUBLIC_BASE_URL or "").rstrip("/")
    return (base + path) if base else ""


def _create_all(c: sqlite3.Connection) -> None:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS devices(
        id            TEXT PRIMARY KEY,
        name          TEXT,
        type          TEXT,
        location      TEXT,
        ratedTemp     REAL,
        ratedHumidity REAL,
        installDate   TEXT,
        lastInspectAt TEXT,
        history       TEXT,
        qrCode        TEXT
    );
    CREATE TABLE IF NOT EXISTS tasks(
        id           TEXT PRIMARY KEY,
        deviceId     TEXT,
        title        TEXT,
        deviceName   TEXT,
        location     TEXT,
        status       TEXT,
        priority     TEXT,
        deadline     TEXT,
        assignee     TEXT,
        startedAt    TEXT,
        completedAt  TEXT,
        inspectionId TEXT
    );
    CREATE TABLE IF NOT EXISTS inspections(
        id            TEXT PRIMARY KEY,
        taskId        TEXT,
        deviceId      TEXT,
        deviceName    TEXT,
        location      TEXT,
        operator      TEXT,
        voiceText     TEXT,
        voiceSlotsJson TEXT,
        visionJson    TEXT,
        sensorJson    TEXT,
        imageId       TEXT,
        level         TEXT,
        confidence    REAL,
        advice        TEXT,
        needHuman     INTEGER DEFAULT 0,
        mock          INTEGER DEFAULT 0,
        stepsJson     TEXT,
        workOrderId   TEXT,
        durationMs    INTEGER,
        capturedAt    TEXT,
        createdAt     TEXT
    );
    CREATE TABLE IF NOT EXISTS findings(
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        inspectionId TEXT,
        item         TEXT,
        value        TEXT,
        abnormal     INTEGER DEFAULT 0,
        basis        TEXT,
        sortOrder    INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS workorders(
        id           TEXT PRIMARY KEY,
        inspectionId TEXT,
        taskId       TEXT,
        deviceId     TEXT,
        deviceName   TEXT,
        level        TEXT,
        description  TEXT,
        assignee     TEXT,
        status       TEXT,
        handleNote   TEXT,
        createdAt    TEXT,
        closedAt     TEXT
    );
    CREATE TABLE IF NOT EXISTS media(
        id           TEXT PRIMARY KEY,
        inspectionId TEXT,
        kind         TEXT,
        fileName     TEXT,
        mimeType     TEXT,
        sizeKb       INTEGER,
        createdAt    TEXT
    );
    CREATE TABLE IF NOT EXISTS schema_version(
        version INTEGER PRIMARY KEY
    );
    CREATE TABLE IF NOT EXISTS sessions(
        id           TEXT PRIMARY KEY,
        taskId       TEXT,
        deviceId     TEXT,
        deviceType   TEXT,
        location     TEXT,
        operator     TEXT,
        createdAt    TEXT,
        updatedAt    TEXT,
        lastInspectionId TEXT
    );
    CREATE TABLE IF NOT EXISTS inspection_memories(
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        inspectionId TEXT,
        sessionId    TEXT,
        deviceId     TEXT,
        deviceType   TEXT,
        level        TEXT,
        summary      TEXT,
        keywords     TEXT,
        capturedAt   TEXT,
        createdAt    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_insp_device ON inspections(deviceId);
    CREATE INDEX IF NOT EXISTS idx_insp_time   ON inspections(createdAt DESC);
    CREATE INDEX IF NOT EXISTS idx_find_insp   ON findings(inspectionId);
    CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_mem_device  ON inspection_memories(deviceId);
    """)


# ---- P0-5: 检查项模板（按设备类型，端侧不再自维护） ----
CHECKLIST_TEMPLATES: dict[str, list[str]] = {
    "低压配电柜": ["柜体外观与标识", "仪表读数", "指示灯状态", "母线接头温度", "线路绝缘", "异味与异响"],
    "高压柜": ["柜体外观", "开关位置指示", "放电痕迹与局放", "母线温度", "SF6 压力", "五防闭锁"],
    "干式变压器": ["绕组温度", "风机运行", "表面清洁与放电痕迹", "温控器指示", "异响与振动", "接地连接"],
    "直流屏": ["电压电流指示", "单体电压", "电池外观（鼓包/漏液）", "充电机状态", "告警指示", "通风散热"],
    "电缆沟": ["盖板完好", "积水情况", "电缆接头温度", "支架与固定", "防火封堵", "异味"],
    "消防器材": ["压力表指针", "有效期标签", "瓶体外观", "喷嘴与软管", "摆放与通道", "巡检卡填写"],
}


def _default_checklist(device_type: str) -> list[dict]:
    names = CHECKLIST_TEMPLATES.get(device_type or "", CHECKLIST_TEMPLATES["低压配电柜"])
    return [{"key": f"C{i + 1}", "name": n, "required": True, "status": "pending"}
            for i, n in enumerate(names)]


def _hash_password(password: str, salt: str = "") -> str:
    salt = salt or uuid.uuid4().hex[:16]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
    return f"pbkdf2$120000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:  # noqa: BLE001
        return False


def _seed_users(c: sqlite3.Connection) -> None:
    """默认账号：admin/admin123、inspector/inspector123（仅内网演示用）。"""
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    now = _now()
    for uid, name, pwd, role, team in (
            ("U-0001", "admin", "admin123", "admin", "运维中心"),
            ("U-0002", "inspector", "inspector123", "inspector", "配电班")):
        c.execute("INSERT INTO users(id,name,role,team,phone,lastLoginAt,createdAt,passwordHash) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (uid, name, role, team, "", "", now, _hash_password(pwd)))


def _backfill_checklists(c: sqlite3.Connection) -> None:
    rows = c.execute("SELECT t.id, d.type FROM tasks t LEFT JOIN devices d "
                     "ON t.deviceId=d.id WHERE t.checklistJson IS NULL").fetchall()
    for r in rows:
        c.execute("UPDATE tasks SET checklistJson=? WHERE id=?",
                  (json.dumps(_default_checklist(r["type"] or ""), ensure_ascii=False), r["id"]))


def _seed(c: sqlite3.Connection) -> None:
    if c.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?)", SEED_DEVICES)
    if c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO tasks(id,deviceId,title,deviceName,location,status,"
            "priority,deadline,assignee) VALUES(?,?,?,?,?,?,?,?,?)", SEED_TASKS)


def init_db() -> None:
    """带版本号的迁移。

    早期开发库只有 3 张表、无 schema_version 且列更少——结构不兼容，直接重建
    （初赛阶段 data/inspect.db 无历史价值，重建后 seed 重新灌入）。
    之后 schema_version=1 存在，走正常增量迁移路径。
    """
    with _conn() as c:
        has_ver = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if not has_ver:
            for t in ("findings", "media", "workorders", "inspections", "tasks", "devices"):
                c.execute(f"DROP TABLE IF EXISTS {t}")
        c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER)")
        v = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        if v < 1:
            _create_all(c)
            _seed(c)
            c.execute("INSERT INTO schema_version VALUES(1)")
        if v < 2:
            # v2 新增：sessions + inspection_memories（会话记忆）
            c.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(
                    id               TEXT PRIMARY KEY,
                    taskId           TEXT, deviceId TEXT, deviceType TEXT,
                    location         TEXT, operator TEXT,
                    createdAt        TEXT, updatedAt TEXT, lastInspectionId TEXT);
                CREATE TABLE IF NOT EXISTS inspection_memories(
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    inspectionId TEXT, sessionId TEXT, deviceId TEXT, deviceType TEXT,
                    level        TEXT, summary TEXT, keywords TEXT,
                    capturedAt   TEXT, createdAt TEXT);
                CREATE INDEX IF NOT EXISTS idx_mem_device ON inspection_memories(deviceId);
            """)
            c.execute("INSERT INTO schema_version VALUES(2)")
        if v < 3:
            # 🟢 P3-1: v3 新增 agent_traces（完整事件流持久化，用于 replay/调试）
            c.executescript("""
                CREATE TABLE IF NOT EXISTS agent_traces(
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    sessionId   TEXT,
                    inspectionId TEXT,
                    taskId      TEXT,
                    deviceId    TEXT,
                    deviceName  TEXT,
                    level       TEXT,
                    confidence  REAL,
                    durationMs  INTEGER,
                    eventsJson  TEXT,          -- 完整事件流 JSON 数组
                    createdAt   TEXT);
                CREATE INDEX IF NOT EXISTS idx_trace_session ON agent_traces(sessionId);
                CREATE INDEX IF NOT EXISTS idx_trace_time ON agent_traces(createdAt DESC);
            """)
            c.execute("INSERT INTO schema_version VALUES(3)")
        if v < 4:
            # 🟢 数据归档能力（生产级运维必备）
            c.executescript("""
                -- 历史归档：超过 90 天的巡检自动归档到此表，主表保持轻量
                CREATE TABLE IF NOT EXISTS archived_inspections(
                    id          TEXT PRIMARY KEY,
                    taskId      TEXT, deviceId TEXT, deviceName TEXT, location TEXT,
                    operator    TEXT, voiceText TEXT,
                    level       TEXT, confidence REAL, advice TEXT, needHuman INTEGER,
                    createdAt   TEXT, archivedAt TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_arch_time ON archived_inspections(createdAt DESC);

                -- 告警日志：LLM 熔断 / RAG 降级 / 工具失败等生产告警
                CREATE TABLE IF NOT EXISTS alert_logs(
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    level       TEXT,             -- info / warn / error / critical
                    category    TEXT,             -- llm / rag / db / tool / vision
                    message     TEXT,
                    detail      TEXT,
                    resolved    INTEGER DEFAULT 0,
                    createdAt   TEXT);
                CREATE INDEX IF NOT EXISTS idx_alert_level ON alert_logs(level);
                CREATE INDEX IF NOT EXISTS idx_alert_time ON alert_logs(createdAt DESC);

                -- 人员档案：operator 不再是 free text
                CREATE TABLE IF NOT EXISTS users(
                    id          TEXT PRIMARY KEY,
                    name        TEXT,
                    role        TEXT DEFAULT 'inspector',
                    team        TEXT,
                    phone       TEXT,
                    lastLoginAt TEXT,
                    createdAt   TEXT);
            """)
            c.execute("INSERT INTO schema_version VALUES(4)")

        # ---- v5: token 用量统计表 ----
        if v < 5:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS token_usage(
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    createdAt        TEXT,
                    model            TEXT,
                    caller           TEXT,   -- plan/decide/react/review/followup/stream/vision
                    sessionId        TEXT,
                    promptTokens     INTEGER DEFAULT 0,
                    completionTokens INTEGER DEFAULT 0,
                    totalTokens      INTEGER DEFAULT 0,
                    costCny          REAL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_token_usage_time ON token_usage(createdAt);
            """)
            c.execute("INSERT INTO schema_version VALUES(5)")

        # ---- v6: P0 端侧优化（检查项 / 幂等键 / 登录鉴权） ----
        if v < 6:
            c.execute("ALTER TABLE tasks ADD COLUMN checklistJson TEXT")
            c.execute("ALTER TABLE inspections ADD COLUMN requestId TEXT DEFAULT ''")
            c.execute("ALTER TABLE users ADD COLUMN passwordHash TEXT DEFAULT ''")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS auth_tokens(
                    token      TEXT PRIMARY KEY,
                    userId     TEXT,
                    kind       TEXT,          -- access / refresh
                    expiresAt  TEXT,
                    revoked    INTEGER DEFAULT 0,
                    createdAt  TEXT);
                CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_tokens(userId);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_insp_reqid
                    ON inspections(requestId) WHERE requestId <> '';
            """)
            c.execute("INSERT INTO schema_version VALUES(6)")
            _seed_users(c)
            _backfill_checklists(c)

        # ---- v7: P1/P2（同步版本号 / 告警处理人 / token 维度） ----
        if v < 7:
            _ensure_column(c, "inspections", "updatedAt", "updatedAt TEXT DEFAULT ''")
            _ensure_column(c, "tasks", "updatedAt", "updatedAt TEXT DEFAULT ''")
            _ensure_column(c, "workorders", "updatedAt", "updatedAt TEXT DEFAULT ''")
            _ensure_column(c, "alert_logs", "resolvedBy", "resolvedBy TEXT DEFAULT ''")
            _ensure_column(c, "alert_logs", "resolvedAt", "resolvedAt TEXT DEFAULT ''")
            _ensure_column(c, "alert_logs", "resolveNote", "resolveNote TEXT DEFAULT ''")
            _ensure_column(c, "token_usage", "userId", "userId TEXT DEFAULT ''")
            _ensure_column(c, "token_usage", "deviceId", "deviceId TEXT DEFAULT ''")
            _ensure_column(c, "token_usage", "traceId", "traceId INTEGER DEFAULT 0")
            # 旧数据回填版本时间
            c.execute("UPDATE inspections SET updatedAt=COALESCE(NULLIF(capturedAt,''),"
                      "createdAt,'') WHERE updatedAt=''")
            c.execute("UPDATE tasks SET updatedAt=COALESCE(NULLIF(completedAt,''),"
                      "NULLIF(startedAt,''),deadline,'') WHERE updatedAt=''")
            c.execute("UPDATE workorders SET updatedAt=COALESCE(NULLIF(closedAt,''),"
                      "createdAt,'') WHERE updatedAt=''")
            c.execute("INSERT INTO schema_version VALUES(7)")


def _ensure_column(c: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """幂等加列（迁移可重复执行，不会因列已存在而中断）。"""
    cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


# ---- P0-3: 登录 / Token（落库，服务重启后仍有效） ----
def get_user_by_name(name: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id,name,role,team,passwordHash FROM users WHERE name=?",
                      (name,)).fetchone()
    return dict(r) if r else None


def get_user(user_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id,name,role,team FROM users WHERE id=?",
                      (user_id,)).fetchone()
    return dict(r) if r else None


def issue_token(user_id: str, kind: str, ttl_minutes: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = (datetime.now() + timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute("INSERT INTO auth_tokens(token,userId,kind,expiresAt,revoked,createdAt) "
                  "VALUES(?,?,?,?,0,?)", (token, user_id, kind, exp, _now()))
    return token


def verify_token(token: str, kind: str = "access") -> dict | None:
    if not token:
        return None
    with _conn() as c:
        r = c.execute("SELECT t.userId,u.name,u.role,u.team FROM auth_tokens t "
                      "LEFT JOIN users u ON u.id=t.userId "
                      "WHERE t.token=? AND t.kind=? AND t.revoked=0 AND t.expiresAt>=?",
                      (token, kind, _now())).fetchone()
    if not r:
        return None
    return {"userId": r["userId"], "name": r["name"] or "",
            "role": r["role"] or "inspector", "team": r["team"] or ""}


def revoke_token(token: str) -> None:
    with _conn() as c:
        c.execute("UPDATE auth_tokens SET revoked=1 WHERE token=?", (token,))


def touch_login(user_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET lastLoginAt=? WHERE id=?", (_now(), user_id))


def get_inspection_by_request_id(request_id: str) -> dict | None:
    if not request_id:
        return None
    with _conn() as c:
        r = c.execute("SELECT id FROM inspections WHERE requestId=?",
                      (request_id,)).fetchone()
    return get_inspection(r["id"]) if r else None


def save_token_usage(model: str, caller: str, prompt_tokens: int,
                     completion_tokens: int, cost_cny: float = 0.0,
                     session_id: str = "", user_id: str = "",
                     device_id: str = "", trace_id: int = 0) -> None:
    """记录一次 LLM 调用的 token 用量（任何失败都静默，不影响主流程）。

    P2-15: userId/deviceId 未直接给出时，从 sessions 反查（operator → users.id）。
    """
    try:
        if session_id and (not user_id or not device_id):
            with _conn() as c0:
                s = c0.execute("SELECT deviceId,operator FROM sessions WHERE id=?",
                               (session_id,)).fetchone()
            if s:
                device_id = device_id or (s["deviceId"] or "")
                if not user_id and s["operator"]:
                    with _conn() as c0:
                        u = c0.execute("SELECT id FROM users WHERE name=?",
                                       (s["operator"],)).fetchone()
                    user_id = (u["id"] if u else "") or ""
        with _conn() as c:
            c.execute(
                "INSERT INTO token_usage(createdAt,model,caller,sessionId,userId,deviceId,"
                "traceId,promptTokens,completionTokens,totalTokens,costCny) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (_now(), model, caller, session_id, user_id, device_id, trace_id,
                 prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, cost_cny))
    except Exception:  # noqa: BLE001
        pass


def get_token_stats(days: int = 7) -> dict:
    """聚合最近 N 天 token 用量：总量 / 按天 / 按调用方。"""
    since = _days_ago(days)
    with _conn() as c:
        total = c.execute(
            "SELECT COALESCE(SUM(promptTokens),0) p, COALESCE(SUM(completionTokens),0) c, "
            "COALESCE(SUM(totalTokens),0) t, COALESCE(SUM(costCny),0) cost, COUNT(*) n "
            "FROM token_usage WHERE createdAt>=?", (since,)).fetchone()
        by_day = c.execute(
            "SELECT substr(createdAt,1,10) day, SUM(totalTokens) tokens, "
            "SUM(costCny) cost, COUNT(*) calls FROM token_usage "
            "WHERE createdAt>=? GROUP BY day ORDER BY day", (since,)).fetchall()
        by_caller = c.execute(
            "SELECT caller, SUM(totalTokens) tokens, SUM(costCny) cost, COUNT(*) calls "
            "FROM token_usage WHERE createdAt>=? GROUP BY caller ORDER BY tokens DESC",
            (since,)).fetchall()
        by_model = c.execute(
            "SELECT model, SUM(totalTokens) tokens, SUM(costCny) cost, COUNT(*) calls "
            "FROM token_usage WHERE createdAt>=? GROUP BY model",
            (since,)).fetchall()
        by_user = c.execute(
            "SELECT userId, SUM(totalTokens) tokens, SUM(costCny) cost, COUNT(*) calls "
            "FROM token_usage WHERE createdAt>=? GROUP BY userId ORDER BY tokens DESC",
            (since,)).fetchall()
        by_device = c.execute(
            "SELECT deviceId, SUM(totalTokens) tokens, SUM(costCny) cost, COUNT(*) calls "
            "FROM token_usage WHERE createdAt>=? GROUP BY deviceId ORDER BY tokens DESC",
            (since,)).fetchall()
        by_session = c.execute(
            "SELECT sessionId, SUM(totalTokens) tokens, SUM(costCny) cost, COUNT(*) calls "
            "FROM token_usage WHERE createdAt>=? GROUP BY sessionId ORDER BY tokens DESC "
            "LIMIT 50", (since,)).fetchall()
    return {
        "days": days, "since": since,
        "total": {"promptTokens": total["p"], "completionTokens": total["c"],
                  "totalTokens": total["t"], "costCny": round(total["cost"], 4),
                  "calls": total["n"]},
        "byDay": [dict(r) for r in by_day],
        "byCaller": [dict(r) for r in by_caller],
        "byModel": [dict(r) for r in by_model],
        # P2-15: 生产排障维度
        "byUser": [dict(r) for r in by_user],
        "byDevice": [dict(r) for r in by_device],
        "bySession": [dict(r) for r in by_session],
    }


# ---- 查询：任务 / 设备 ----
def _load_checklist(raw: str | None) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _task_item(r: sqlite3.Row) -> TaskItem:
    d = dict(r)
    checklist = _load_checklist(d.pop("checklistJson", None))
    if not d.get("inspectionId"):
        d["inspectionId"] = ""
    d["updatedAt"] = d.get("updatedAt") or ""
    d["checklist"] = checklist
    d["checklistTotal"] = len(checklist)
    d["checklistDone"] = sum(1 for x in checklist if x.get("status") in ("done", "skipped"))
    # 强制校验保证同一 assignee 最多一个进行中，故"进行中"即当前任务
    d["isCurrent"] = d.get("status") == "进行中"
    return TaskItem(**d)


def list_tasks(status: str = "", device_id: str = "") -> list[TaskItem]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,deviceId,title,deviceName,location,status,priority,deadline,"
            "assignee,inspectionId,checklistJson,updatedAt FROM tasks ORDER BY id").fetchall()
    items = [_task_item(r) for r in rows]
    if status:
        items = [t for t in items if t.status == status]
    if device_id:
        items = [t for t in items if t.deviceId == device_id]
    return items


def get_task(task_id: str) -> TaskItem | None:
    with _conn() as c:
        r = c.execute("SELECT id,deviceId,title,deviceName,location,status,priority,"
                      "deadline,assignee,inspectionId,checklistJson,updatedAt "
                      "FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_item(r) if r else None


def update_task_status(task_id: str, status: str, inspection_id: str = "") -> TaskItem | None:
    """P0-2: 强制"一人一个进行中"——开始新任务时同 assignee 的其他进行中任务回到待巡检。"""
    now = _now()
    with _conn() as c:
        row = c.execute("SELECT assignee,checklistJson FROM tasks WHERE id=?",
                        (task_id,)).fetchone()
        assignee = (row["assignee"] if row else "") or ""
        checklist = _load_checklist(row["checklistJson"] if row else None)
        if status == "进行中":
            if assignee:
                c.execute("UPDATE tasks SET status='待巡检', updatedAt=? WHERE assignee=? "
                          "AND status='进行中' AND id<>?", (now, assignee, task_id))
            c.execute("UPDATE tasks SET status=?, startedAt=?, updatedAt=? WHERE id=?",
                      (status, now, now, task_id))
        elif status == "已完成":
            for item in checklist:
                item["status"] = "done"
            c.execute("UPDATE tasks SET status=?, completedAt=?, inspectionId=?, "
                      "checklistJson=?, updatedAt=? WHERE id=?",
                      (status, now, inspection_id,
                       json.dumps(checklist, ensure_ascii=False), now, task_id))
        else:
            c.execute("UPDATE tasks SET status=?, updatedAt=? WHERE id=?",
                      (status, now, task_id))
    return get_task(task_id)


def list_devices(device_type: str = "") -> list[DeviceProfile]:
    with _conn() as c:
        if device_type:
            rows = c.execute("SELECT * FROM devices WHERE type=? ORDER BY id",
                             (device_type,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM devices ORDER BY id").fetchall()
    return [DeviceProfile(**dict(r)) for r in rows]


def get_device_profile(device_id: str) -> DeviceProfile:
    with _conn() as c:
        r = c.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    if r:
        return DeviceProfile(**dict(r))
    return DeviceProfile(id=device_id, history="无历史台账")


# ---- 查询：巡检 ----
def _inspection_brief(d: dict, base_url: str = "") -> SyncInspection:
    """P1-6：同步/列表共用的固定摘要结构（不含 findings / steps）。"""
    image = f"/media/{d['imageId']}" if d.get("imageId") else ""
    return SyncInspection(
        inspectionId=d.get("id") or "",
        taskId=d.get("taskId") or "",
        deviceId=d.get("deviceId") or "",
        deviceName=d.get("deviceName") or "",
        location=d.get("location") or "",
        operator=d.get("operator") or "",
        level=d.get("level") or "正常",
        confidence=float(d.get("confidence") or 0.0),
        advice=d.get("advice") or "",
        imageUrl=image,
        imageAbsoluteUrl=absolute_media_url(image, base_url),
        workOrderId=d.get("workOrderId") or "",
        capturedAt=d.get("capturedAt") or "",
        createdAt=d.get("createdAt") or "",
        updatedAt=d.get("updatedAt") or "",
        needHuman=bool(d.get("needHuman")),
        mock=bool(d.get("mock")),
    )


def inspection_to_resp(d: dict, base_url: str = "") -> InspectResp:
    """P1-11：历史详情与 WS final 用同一个 InspectResp DTO。"""
    image = f"/media/{d['imageId']}" if d.get("imageId") else ""
    return InspectResp(
        sessionId=d.get("sessionId") or "",
        inspectionId=d.get("id") or "",
        imageUrl=image,
        imageAbsoluteUrl=absolute_media_url(image, base_url),
        level=d.get("level") or "正常",
        confidence=float(d.get("confidence") or 0.0),
        advice=d.get("advice") or "",
        findings=d.get("findings") or [],
        voiceSlots=d.get("voiceSlots") or {},
        vision=d.get("vision") or {},
        steps=d.get("steps") or [],
        workOrderId=d.get("workOrderId") or None,
        needHuman=bool(d.get("needHuman")),
        mock=bool(d.get("mock")),
        durationMs=int(d.get("durationMs") or 0),
        taskId=d.get("taskId") or "",
        deviceId=d.get("deviceId") or "",
        deviceName=d.get("deviceName") or "",
        location=d.get("location") or "",
        operator=d.get("operator") or "",
        capturedAt=d.get("capturedAt") or "",
        voiceText=d.get("voiceText") or "",
    )


def list_inspections(limit: int = 50, level: str = "", device_id: str = "",
                     start_time: str = "", end_time: str = "",
                     base_url: str = "") -> list[SyncInspection]:
    sql = "SELECT * FROM inspections WHERE 1=1"
    args: list = []
    if level:
        sql += " AND level=?"
        args.append(level)
    if device_id:
        sql += " AND deviceId=?"
        args.append(device_id)
    if start_time:
        sql += " AND COALESCE(NULLIF(capturedAt,''),createdAt)>=?"
        args.append(start_time)
    if end_time:
        sql += " AND COALESCE(NULLIF(capturedAt,''),createdAt)<=?"
        args.append(end_time)
    sql += " ORDER BY createdAt DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [_inspection_brief(dict(r), base_url) for r in rows]


def get_inspection(inspection_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    with _conn() as c2:
        frows = c2.execute("SELECT item,value,abnormal,basis FROM findings "
                           "WHERE inspectionId=? ORDER BY sortOrder", (inspection_id,)).fetchall()
    d["findings"] = [dict(f) for f in frows]
    d["voiceSlots"] = _load_json(d.get("voiceSlotsJson"))
    d["vision"] = _load_json(d.get("visionJson"))
    d["steps"] = _load_json(d.get("stepsJson"))
    return d


def _load_json(s: str | None):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return None


# ---- 工单 ----
def create_workorder(task_id: str, device_id: str, device_name: str,
                     level: str, description: str,
                     inspection_id: str = "") -> WorkOrder:
    now = _now()
    wo = WorkOrder(id="WO-" + uuid.uuid4().hex[:6].upper(), inspectionId=inspection_id,
                   taskId=task_id, deviceId=device_id, deviceName=device_name,
                   level=level, description=description, status="待处理",
                   createdAt=now, updatedAt=now)
    with _conn() as c:
        c.execute("INSERT INTO workorders(id,inspectionId,taskId,deviceId,deviceName,"
                  "level,description,assignee,status,handleNote,createdAt,closedAt,updatedAt) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wo.id, wo.inspectionId, wo.taskId, wo.deviceId, wo.deviceName,
                   wo.level, wo.description, wo.assignee, wo.status, wo.handleNote,
                   wo.createdAt, wo.closedAt, wo.updatedAt))
    return wo


def list_workorders(status: str = "", level: str = "", device_id: str = "") -> list[WorkOrder]:
    sql = "SELECT * FROM workorders WHERE 1=1"
    args: list = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if level:
        sql += " AND level=?"
        args.append(level)
    if device_id:
        sql += " AND deviceId=?"
        args.append(device_id)
    sql += " ORDER BY createdAt DESC"
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [WorkOrder(**dict(r)) for r in rows]


def get_workorder(wo_id: str) -> WorkOrder | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM workorders WHERE id=?", (wo_id,)).fetchone()
    return WorkOrder(**dict(r)) if r else None


def update_workorder_status(wo_id: str, status: str, handle_note: str = "") -> WorkOrder | None:
    now = _now()
    closed_at = now if status == "已闭环" else ""
    with _conn() as c:
        c.execute("UPDATE workorders SET status=?, handleNote=?, closedAt=?, updatedAt=? "
                  "WHERE id=?", (status, handle_note, closed_at, now, wo_id))
    return get_workorder(wo_id)


# ---- 巡检落库（run 成功后的最后一步） ----
def finalize_inspection(req: InspectReq, resp: InspectResp,
                        image_bytes: bytes = b"",
                        request_id: str = "") -> InspectResp:
    """把一次巡检写进 inspections/findings/media，并回填 inspectionId/imageUrl。"""
    iid = f"IN-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:4]}"
    now = _now()
    image_file = ""
    if image_bytes:
        image_file = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"
        (settings.UPLOAD_DIR / image_file).write_bytes(image_bytes)
        with _conn() as c:
            c.execute("INSERT INTO media(id,inspectionId,kind,fileName,mimeType,sizeKb,createdAt) "
                      "VALUES(?,?,?,?,?,?,?)",
                      ("MD-" + uuid.uuid4().hex[:6], iid, "image", image_file,
                       "image/jpeg", len(image_bytes) // 1024, _now()))

    sensor_json = req.sensor.model_dump_json() if req.sensor else ""
    with _conn() as c:
        c.execute(
            "INSERT INTO inspections(id,taskId,deviceId,deviceName,location,operator,"
            "voiceText,voiceSlotsJson,visionJson,sensorJson,imageId,level,confidence,"
            "advice,needHuman,mock,stepsJson,workOrderId,durationMs,capturedAt,createdAt,"
            "requestId,updatedAt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, req.taskId, req.deviceId, req.deviceName, req.location, req.operator,
             req.voiceText, resp.voiceSlots.model_dump_json(),
             resp.vision.model_dump_json(), sensor_json,
             image_file,
             resp.level, resp.confidence, resp.advice,
             1 if resp.needHuman else 0, 1 if resp.mock else 0,
             json.dumps([s.model_dump() for s in resp.steps], ensure_ascii=False),
             resp.workOrderId, resp.durationMs, req.capturedAt, now, request_id, now))
        for i, f in enumerate(resp.findings):
            c.execute("INSERT INTO findings(inspectionId,item,value,abnormal,basis,sortOrder) "
                      "VALUES(?,?,?,?,?,?)",
                      (iid, f.item, f.value, 1 if f.abnormal else 0, f.basis, i))

    resp.inspectionId = iid
    resp.imageUrl = f"/media/{image_file}" if image_file else ""
    # 配了 PUBLIC_BASE_URL 时 WS final 也能直接拿到完整地址；否则由路由层按请求来源补
    resp.imageAbsoluteUrl = absolute_media_url(resp.imageUrl)
    return resp

# ============= P1-6/7: 端侧同步快照 + 冲突仲裁 =============
# 增量与版本统一用 updatedAt（服务端维护），不再混用 capturedAt / createdAt。
CONFLICT_ALLOWED: dict[str, set[str]] = {
    "inspections": {"level", "confidence", "advice", "needHuman"},
    "workorders": {"status", "handleNote", "assignee"},
    "tasks": {"status", "inspectionId"},
}


def get_sync_snapshot(device_id: str = "", since: str = "", base_url: str = "") -> SyncSnapshot:
    """端侧启动全量（不带 since）/ 之后增量（带 since）；since 比较 updatedAt。"""
    TASK_COLS = ("SELECT id,deviceId,title,deviceName,location,status,priority,deadline,"
                 "assignee,inspectionId,checklistJson,updatedAt FROM tasks ")
    dev = " AND deviceId=?" if device_id else ""
    dev_args: tuple = (device_id,) if device_id else ()
    with _conn() as c:
        if since:
            irows = c.execute("SELECT * FROM inspections WHERE updatedAt > ?" + dev
                              + " ORDER BY updatedAt ASC LIMIT 5000",
                              (since,) + dev_args).fetchall()
            wrows = c.execute("SELECT * FROM workorders WHERE updatedAt > ?" + dev
                              + " ORDER BY updatedAt ASC LIMIT 5000",
                              (since,) + dev_args).fetchall()
            trows = c.execute(TASK_COLS + "WHERE updatedAt > ?" + dev
                              + " ORDER BY updatedAt ASC", (since,) + dev_args).fetchall()
        else:
            irows = c.execute("SELECT * FROM inspections WHERE 1=1" + dev
                              + " ORDER BY updatedAt DESC LIMIT 5000", dev_args).fetchall()
            wrows = c.execute("SELECT * FROM workorders WHERE 1=1" + dev
                              + " ORDER BY updatedAt DESC LIMIT 5000", dev_args).fetchall()
            trows = c.execute(TASK_COLS + "WHERE 1=1" + dev + " ORDER BY id",
                              dev_args).fetchall()
    return SyncSnapshot(
        since=since,
        sinceField="updatedAt",
        serverTime=_now(),
        devices=list_devices(),
        tasks=[_task_item(r) for r in trows],
        workorders=[WorkOrder(**dict(r)) for r in wrows],
        inspections=[_inspection_brief(dict(r), base_url) for r in irows],
        deleted=[],
    )


def resolve_conflict(table: str, rec_id: str, cloud_version: str,
                     device_changes: dict) -> ConflictResp:
    """冲突仲裁规则（白名单 + 版本比对）：

    - 只接受白名单字段；
    - 若端侧记录的 cloud_version 与服务端当前 updatedAt 一致，说明云端没被别人改过，
      接受端侧改动（winner=device）；
    - 否则云端记录已变更，以云端为准（winner=cloud）。
    """
    allowed = CONFLICT_ALLOWED.get(table, set())
    changes = dict(device_changes or {})
    applied = [k for k in changes if k in allowed]
    rejected = [k for k in changes if k not in allowed]

    def _final() -> dict | None:
        with _conn() as c:
            r = c.execute(f"SELECT * FROM {table} WHERE id=?", (rec_id,)).fetchone()
        return dict(r) if r else None

    cur = _final()
    if not cur:
        return ConflictResp(table=table, id=rec_id, resolved=False, winner="cloud",
                            applied=[], rejected=rejected, final={},
                            message="云端不存在该记录，请以云端列表为准")

    current_version = cur.get("updatedAt") or cur.get("createdAt") or ""
    if applied and cloud_version and cloud_version == current_version:
        now = _now()
        sets, args = [], []
        for k in applied:
            v = changes[k]
            sets.append(f"{k}=?")
            args.append(int(bool(v)) if k == "needHuman" else v)
        sets.append("updatedAt=?")
        args.append(now)
        with _conn() as c:
            c.execute(f"UPDATE {table} SET {','.join(sets)} WHERE id=?", (*args, rec_id))
        return ConflictResp(table=table, id=rec_id, resolved=True, winner="device",
                            cloudVersion=now, applied=applied, rejected=rejected,
                            final=_final() or {}, message="云端版本未变，已接受端侧改动")

    return ConflictResp(table=table, id=rec_id, resolved=True, winner="cloud",
                        cloudVersion=current_version, applied=[], rejected=rejected,
                        final=cur, message="云端记录已变更，以云端为准")


# ============= 会话记忆 / 历史巡检记忆 =============

def upsert_session(session_id: str, req: "InspectReq") -> None:
    """同一会话（Web 端同一 sessionId 多次巡检）自动累积记忆。"""
    now = _now()
    with _conn() as c:
        existing = c.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if existing:
            c.execute("UPDATE sessions SET updatedAt=? WHERE id=?", (now, session_id))
        else:
            c.execute(
                "INSERT INTO sessions(id,taskId,deviceId,deviceType,location,operator,createdAt,updatedAt) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (session_id, req.taskId or "", req.deviceId or "", req.deviceType or "",
                 req.location or "", req.operator or "", now, now))


def save_inspection_memory(session_id: str, req: "InspectReq", resp: "InspectResp") -> None:
    """巡检完成后自动写入记忆表（结构化摘要 + 关键词，供 RAG 再次命中）。"""
    keywords = list({req.deviceType or "", req.deviceName or "", req.voiceText or "",
                    resp.level} | {f.item + ":" + f.value for f in resp.findings})
    keywords_str = " | ".join(keywords[:12])
    summary_parts = [f"设备 {req.deviceName}({req.deviceType})",
                     f"巡检结果 {resp.level} 置信度 {resp.confidence:.2f}"]
    if resp.findings:
        abnormal = [f.item for f in resp.findings if f.abnormal]
        if abnormal:
            summary_parts.append("异常项: " + "、".join(abnormal[:4]))
    summary_parts.append(resp.advice[:80] if resp.advice else "")
    summary = "；".join(summary_parts)
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO inspection_memories(inspectionId,sessionId,deviceId,deviceType,"
            "level,summary,keywords,capturedAt,createdAt) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (resp.inspectionId or "", session_id, req.deviceId or "", req.deviceType or "",
             resp.level, summary, keywords_str, req.capturedAt or now, now))
        c.execute("UPDATE sessions SET lastInspectionId=?, updatedAt=? WHERE id=?",
                  (resp.inspectionId or "", now, session_id))


def load_recent_memories(device_id: str | None = None, limit: int = 5) -> list[dict]:
    """加载最近的历史巡检记忆（按设备类型优先）。"""
    if not device_id:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM inspection_memories WHERE deviceId=? ORDER BY capturedAt DESC LIMIT ?",
            (device_id, limit)).fetchall()
        return [dict(r) for r in rows]


def load_all_memories(limit: int = 20) -> list[dict]:
    """加载所有历史巡检记忆（无设备过滤，用于 RAG 索引构建）。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM inspection_memories ORDER BY capturedAt DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ============= 🟢 P3-1: Trace 持久化 =============

def save_trace(session_id: str, events: list[dict], resp: "InspectResp",
               req: "InspectReq", duration_ms: int) -> None:
    """巡检完成后把完整事件流异步存 DB（用于 replay/调试）。"""
    import json as _json
    now = _now()
    events_serializable = []
    for ev in events:
        # 把 Pydantic 对象转 dict
        clean = {}
        for k, v in ev.items():
            if hasattr(v, "model_dump"):
                clean[k] = v.model_dump()
            else:
                clean[k] = v
        clean.setdefault("timestamp", now)   # P2-13: 事件时间（同一轮内精度到秒，顺序看 seq）
        events_serializable.append(clean)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO agent_traces(sessionId,inspectionId,taskId,deviceId,deviceName,"
            "level,confidence,durationMs,eventsJson,createdAt) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (session_id, resp.inspectionId or "", req.taskId or "",
             req.deviceId or "", req.deviceName or "",
             resp.level, resp.confidence, duration_ms,
             _json.dumps(events_serializable, ensure_ascii=False), now))
        # P2-15：把本轮 token 记录回填 traceId，Token 统计可按 Trace 下钻
        if session_id:
            c.execute("UPDATE token_usage SET traceId=? WHERE sessionId=? AND traceId=0",
                      (cur.lastrowid, session_id))


def _normalize_events(events: list, fallback_ts: str = "") -> list[dict]:
    """P2-13：把历史/新产生的异构事件统一成 {seq,type,timestamp,stepName,payload}。"""
    out = []
    for i, ev in enumerate(events or []):
        if not isinstance(ev, dict):
            out.append({"seq": i + 1, "type": "raw", "timestamp": fallback_ts,
                        "stepName": "", "payload": {"value": str(ev)}})
            continue
        typ = ev.get("type") or "unknown"
        step = ev.get("step") if isinstance(ev.get("step"), dict) else None
        if ev.get("data") is not None:
            payload = ev["data"]
        elif ev.get("payload") is not None:
            payload = ev["payload"]
        elif ev.get("subStep") is not None:
            payload = ev["subStep"]
        elif step is not None:
            payload = step
        elif ev.get("memories") is not None:
            payload = {"memories": ev["memories"]}
        elif ev.get("text") is not None:
            payload = {"text": ev["text"]}
        else:
            payload = {k: v for k, v in ev.items()
                       if k not in ("type", "timestamp", "ts", "stepName")}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        out.append({
            "seq": i + 1,
            "type": typ,
            "timestamp": ev.get("timestamp") or ev.get("ts") or fallback_ts,
            "stepName": ev.get("stepName") or (step or {}).get("name", "") or "",
            "payload": payload,
        })
    return out


def get_trace(trace_id: int) -> dict | None:
    """单条 Trace 查询（/api/v1/traces/{id}），事件已标准化、按 seq 可直接回放。"""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM agent_traces WHERE id=?", (trace_id,)).fetchone()
    if not row:
        return None
    import json as _json
    d = dict(row)
    raw = _json.loads(d.pop("eventsJson") or "[]")
    d["events"] = _normalize_events(raw, d.get("createdAt") or "")
    d["eventCount"] = len(d["events"])
    return d


def list_traces(device_id: str | None = None, limit: int = 20, level: str = "",
                start_time: str = "", end_time: str = "") -> list[dict]:
    """最近的 Trace 列表（不含 events 大字段，轻量）。"""
    sql = ("SELECT id,sessionId,inspectionId,deviceId,deviceName,level,confidence,"
           "durationMs,createdAt FROM agent_traces WHERE 1=1")
    args: list = []
    if device_id:
        sql += " AND deviceId=?"
        args.append(device_id)
    if level:
        sql += " AND level=?"
        args.append(level)
    if start_time:
        sql += " AND createdAt>=?"
        args.append(start_time)
    if end_time:
        sql += " AND createdAt<=?"
        args.append(end_time)
    sql += " ORDER BY createdAt DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


# ============= 🟢 数据归档 / 告警日志 =============

def archive_old_data(days: int = 90) -> dict:
    """把超过 N 天的巡检从主表移动到 archived_inspections（主表保持轻量）。"""
    now = _now()
    cutoff = _days_ago(days)
    with _conn() as c:
        # 1. 迁到归档表
        moved = c.execute(
            "INSERT INTO archived_inspections(id,taskId,deviceId,deviceName,location,"
            "operator,voiceText,level,confidence,advice,needHuman,createdAt,archivedAt) "
            "SELECT id,taskId,deviceId,deviceName,location,operator,voiceText,"
            "level,confidence,advice,needHuman,createdAt,? "
            "FROM inspections WHERE createdAt < ? "
            "AND id NOT IN (SELECT inspectionId FROM workorders WHERE status='待处理')",
            (now, cutoff)).rowcount
        # 2. 删主表
        c.execute("DELETE FROM inspections WHERE createdAt < ? "
                  "AND id NOT IN (SELECT inspectionId FROM workorders WHERE status='待处理')",
                  (cutoff,))
        # 3. 同步删关联
        c.execute("DELETE FROM findings WHERE inspectionId NOT IN (SELECT id FROM inspections)")
        c.execute("DELETE FROM media WHERE inspectionId NOT IN (SELECT id FROM inspections)")
        c.execute("DELETE FROM inspection_memories WHERE inspectionId NOT IN "
                  "(SELECT id FROM inspections) AND inspectionId != ''")
    return {"archived": moved, "cutoff": cutoff}


def cleanup_expired_memories(days: int = 180) -> int:
    """清理超过 N 天的历史记忆（避免老记忆污染 RAG 相关性）。"""
    cutoff = _days_ago(days)
    with _conn() as c:
        return c.execute("DELETE FROM inspection_memories WHERE capturedAt < ?",
                         (cutoff,)).rowcount


def cleanup_old_traces(days: int = 30) -> int:
    """清理超过 N 天的 Trace（eventsJson 大，占空间）。"""
    cutoff = _days_ago(days)
    with _conn() as c:
        return c.execute("DELETE FROM agent_traces WHERE createdAt < ?", (cutoff,)).rowcount


def cleanup_old_media(days: int = 90) -> dict:
    """P1-12：清理已归档巡检的媒体文件与登记（保留期内或主表仍存在的保留）。

    只删“超过 N 天且对应巡检已不在主表（已归档）”的记录，避免报告页图片 404。
    """
    cutoff = _days_ago(days)
    with _conn() as c:
        rows = c.execute(
            "SELECT fileName FROM media WHERE createdAt < ? "
            "AND inspectionId NOT IN (SELECT id FROM inspections)", (cutoff,)).fetchall()
        names = [r["fileName"] for r in rows if r["fileName"]]
    files = 0
    for name in names:
        p = settings.UPLOAD_DIR / name
        try:
            if p.is_file():
                p.unlink()
                files += 1
        except OSError:
            continue
    with _conn() as c:
        rows = c.execute(
            "DELETE FROM media WHERE createdAt < ? "
            "AND inspectionId NOT IN (SELECT id FROM inspections)", (cutoff,)).rowcount
    return {"rows": rows, "files": files, "retentionDays": days}


def log_alert(level: str, category: str, message: str, detail: str = "") -> None:
    """生产告警日志（LLM 熔断/RAG 降级/工具失败等）。"""
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO alert_logs(level,category,message,detail,createdAt) "
            "VALUES(?,?,?,?,?)",
            (level, category, message, detail[:500], now))


def list_alerts(unresolved_only: bool = True, limit: int = 50, level: str = "",
                category: str = "", start_time: str = "", end_time: str = "") -> list[dict]:
    """告警列表（/api/v1/alerts）。"""
    sql = "SELECT * FROM alert_logs WHERE 1=1"
    args: list = []
    if unresolved_only:
        sql += " AND resolved=0"
    if level:
        sql += " AND level=?"
        args.append(level)
    if category:
        sql += " AND category=?"
        args.append(category)
    if start_time:
        sql += " AND createdAt>=?"
        args.append(start_time)
    if end_time:
        sql += " AND createdAt<=?"
        args.append(end_time)
    sql += " ORDER BY createdAt DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def resolve_alert(alert_id: int, note: str = "", user_id: str = "") -> dict | None:
    """P2-14：标记已处理并记录处理人/时间/备注；返回最新告警。"""
    now = _now()
    with _conn() as c:
        ok = c.execute("UPDATE alert_logs SET resolved=1, resolvedBy=?, resolvedAt=?, "
                       "resolveNote=? WHERE id=?", (user_id, now, note, alert_id)).rowcount > 0
        if not ok:
            return None
        r = c.execute("SELECT * FROM alert_logs WHERE id=?", (alert_id,)).fetchone()
    d = dict(r)
    d["resolved"] = bool(d.get("resolved"))
    return d


# ---- 内部：日期工具 ----
def _days_ago(n: int) -> str:
    """返回 N 天前的 YYYY-MM-DD HH:MM:SS 字符串。"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")
