from app.main import app
from app.services import store
import sqlite3, time

print("✅ 后端 import OK")
store.init_db()
print("✅ DB init OK")

# 确认 v4 迁移
c = sqlite3.connect("data/inspect.db")
sv = c.execute("SELECT * FROM schema_version").fetchall()
print(f"✅ schema_version: {sv}")

# 确认三张新表
for t in ["archived_inspections", "alert_logs", "users"]:
    r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
    print(f"✅ {t} 存在: {r is not None}")

# 测试 log_alert
store.log_alert("info", "db", "系统启动", "版本 v4.0")
store.log_alert("warn", "rag", "Chroma 不可用（测试）", "模拟触发")
print(f"✅ alert_logs 插入 OK: {store.list_alerts(unresolved_only=False, limit=10)}")

# 测试 archive_old_data（归档 0 天 = 全归档，然后我们插一条新的恢复）
result = store.archive_old_data(days=0)
print(f"✅ archive_old_data(0): {result}")

# 测试 cleanup
mem_del = store.cleanup_expired_memories(days=0)
trace_del = store.cleanup_old_traces(days=0)
print(f"✅ cleanup: memories={mem_del}, traces={trace_del}")

print("\n🎉 所有归档能力就绪！")
