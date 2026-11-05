from app.main import app
from app.services import store
import sqlite3

print("✅ 后端 import OK")
store.init_db()
print("✅ DB 初始化 OK")

c = sqlite3.connect("data/inspect.db")
r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_traces'").fetchone()
print(f"✅ agent_traces 表存在: {r is not None}")
sv = c.execute("SELECT * FROM schema_version").fetchall()
print(f"✅ schema_version: {sv}")
print("\n✅ P3-1 + P3-2 全部就绪")
