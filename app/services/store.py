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
from app.schemas import (Finding, InspectReq, InspectResp, TaskItem,
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
                     session_id: str = "") -> None:
    """记录一次 LLM 调用的 token 用量（任何失败都静默，不影响主流程）。"""
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO token_usage(createdAt,model,caller,sessionId,"
                "promptTokens,completionTokens,totalTokens,costCny) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (_now(), model, caller, session_id, prompt_tokens,
                 completion_tokens, prompt_tokens + completion_tokens, cost_cny))
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
    return {
        "days": days, "since": since,
        "total": {"promptTokens": total["p"], "completionTokens": total["c"],
                  "totalTokens": total["t"], "costCny": round(total["cost"], 4),
                  "calls": total["n"]},
        "byDay": [dict(r) for r in by_day],
        "byCaller": [dict(r) for r in by_caller],
        "byModel": [dict(r) for r in by_model],
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
    d["checklist"] = checklist
    d["checklistTotal"] = len(checklist)
    d["checklistDone"] = sum(1 for x in checklist if x.get("status") in ("done", "skipped"))
    # 强制校验保证同一 assignee 最多一个进行中，故"进行中"即当前任务
    d["isCurrent"] = d.get("status") == "进行中"
    return TaskItem(**d)


def list_tasks() -> list[TaskItem]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,deviceId,title,deviceName,location,status,priority,"
            "deadline,assignee,inspectionId,checklistJson FROM tasks ORDER BY id").fetchall()
    return [_task_item(r) for r in rows]


def get_task(task_id: str) -> TaskItem | None:
    with _conn() as c:
        r = c.execute("SELECT id,deviceId,title,deviceName,location,status,priority,"
                      "deadline,assignee,inspectionId,checklistJson FROM tasks WHERE id=?",
                      (task_id,)).fetchone()
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
                c.execute("UPDATE tasks SET status='待巡检' WHERE assignee=? "
                          "AND status='进行中' AND id<>?", (assignee, task_id))
            c.execute("UPDATE tasks SET status=?, startedAt=? WHERE id=?",
                      (status, now, task_id))
        elif status == "已完成":
            for item in checklist:
                item["status"] = "done"
            c.execute("UPDATE tasks SET status=?, completedAt=?, inspectionId=?, "
                      "checklistJson=? WHERE id=?",
                      (status, now, inspection_id,
                       json.dumps(checklist, ensure_ascii=False), task_id))
        else:
            c.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    return get_task(task_id)


def list_devices() -> list[DeviceProfile]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM devices ORDER BY id").fetchall()
    return [DeviceProfile(**dict(r)) for r in rows]


def get_device_profile(device_id: str) -> DeviceProfile:
    with _conn() as c:
        r = c.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    if r:
        return DeviceProfile(**dict(r))
    return DeviceProfile(id=device_id, history="无历史台账")


# ---- 查询：巡检 ----
def list_inspections(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM inspections ORDER BY createdAt DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


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
    wo = WorkOrder(id="WO-" + uuid.uuid4().hex[:6].upper(), inspectionId=inspection_id,
                   taskId=task_id, deviceId=device_id, deviceName=device_name,
                   level=level, description=description, status="待处理", createdAt=_now())
    with _conn() as c:
        c.execute("INSERT INTO workorders(id,inspectionId,taskId,deviceId,deviceName,"
                  "level,description,assignee,status,handleNote,createdAt,closedAt) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wo.id, wo.inspectionId, wo.taskId, wo.deviceId, wo.deviceName,
                   wo.level, wo.description, wo.assignee, wo.status, wo.handleNote,
                   wo.createdAt, wo.closedAt))
    return wo


def list_workorders() -> list[WorkOrder]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM workorders ORDER BY createdAt DESC").fetchall()
    return [WorkOrder(**dict(r)) for r in rows]


def get_workorder(wo_id: str) -> WorkOrder | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM workorders WHERE id=?", (wo_id,)).fetchone()
    return WorkOrder(**dict(r)) if r else None


def update_workorder_status(wo_id: str, status: str, handle_note: str = "") -> WorkOrder | None:
    closed_at = _now() if status == "已闭环" else ""
    with _conn() as c:
        c.execute("UPDATE workorders SET status=?, handleNote=?, closedAt=? WHERE id=?",
                  (status, handle_note, closed_at, wo_id))
    return get_workorder(wo_id)


# ---- 巡检落库（run 成功后的最后一步） ----
def finalize_inspection(req: InspectReq, resp: InspectResp,
                        image_bytes: bytes = b"",
                        request_id: str = "") -> InspectResp:
    """把一次巡检写进 inspections/findings/media，并回填 inspectionId/imageUrl。"""
    iid = f"IN-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:4]}"
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
            "advice,needHuman,mock,stepsJson,workOrderId,durationMs,capturedAt,createdAt,requestId) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, req.taskId, req.deviceId, req.deviceName, req.location, req.operator,
             req.voiceText, resp.voiceSlots.model_dump_json(),
             resp.vision.model_dump_json(), sensor_json,
             image_file,
             resp.level, resp.confidence, resp.advice,
             1 if resp.needHuman else 0, 1 if resp.mock else 0,
             json.dumps([s.model_dump() for s in resp.steps], ensure_ascii=False),
             resp.workOrderId, resp.durationMs, req.capturedAt, _now(), request_id))
        for i, f in enumerate(resp.findings):
            c.execute("INSERT INTO findings(inspectionId,item,value,abnormal,basis,sortOrder) "
                      "VALUES(?,?,?,?,?,?)",
                      (iid, f.item, f.value, 1 if f.abnormal else 0, f.basis, i))

    resp.inspectionId = iid
    resp.imageUrl = f"/media/{image_file}" if image_file else ""
    return resp

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
        events_serializable.append(clean)
    with _conn() as c:
        c.execute(
            "INSERT INTO agent_traces(sessionId,inspectionId,taskId,deviceId,deviceName,"
            "level,confidence,durationMs,eventsJson,createdAt) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (session_id, resp.inspectionId or "", req.taskId or "",
             req.deviceId or "", req.deviceName or "",
             resp.level, resp.confidence, duration_ms,
             _json.dumps(events_serializable, ensure_ascii=False), now))


def get_trace(trace_id: int) -> dict | None:
    """单条 Trace 查询（/api/v1/traces/{id}）。"""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM agent_traces WHERE id=?", (trace_id,)).fetchone()
    if not row:
        return None
    import json as _json
    d = dict(row)
    d["events"] = _json.loads(d.pop("eventsJson") or "[]")
    return d


def list_traces(device_id: str | None = None, limit: int = 20) -> list[dict]:
    """最近的 Trace 列表（不含 events 大字段，轻量）。"""
    with _conn() as c:
        if device_id:
            rows = c.execute(
                "SELECT id,sessionId,inspectionId,deviceId,deviceName,level,confidence,durationMs,createdAt "
                "FROM agent_traces WHERE deviceId=? ORDER BY createdAt DESC LIMIT ?",
                (device_id, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT id,sessionId,inspectionId,deviceId,deviceName,level,confidence,durationMs,createdAt "
                "FROM agent_traces ORDER BY createdAt DESC LIMIT ?", (limit,)).fetchall()
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


def log_alert(level: str, category: str, message: str, detail: str = "") -> None:
    """生产告警日志（LLM 熔断/RAG 降级/工具失败等）。"""
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO alert_logs(level,category,message,detail,createdAt) "
            "VALUES(?,?,?,?,?)",
            (level, category, message, detail[:500], now))


def list_alerts(unresolved_only: bool = True, limit: int = 50) -> list[dict]:
    """告警列表（/api/v1/alerts）。"""
    with _conn() as c:
        if unresolved_only:
            rows = c.execute(
                "SELECT * FROM alert_logs WHERE resolved=0 ORDER BY createdAt DESC LIMIT ?",
                (limit,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM alert_logs ORDER BY createdAt DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def resolve_alert(alert_id: int) -> bool:
    """标记告警为已处理。"""
    now = _now()
    with _conn() as c:
        return c.execute("UPDATE alert_logs SET resolved=1 WHERE id=?", (alert_id,)).rowcount > 0


# ---- 内部：日期工具 ----
def _days_ago(n: int) -> str:
    """返回 N 天前的 YYYY-MM-DD HH:MM:SS 字符串。"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")
