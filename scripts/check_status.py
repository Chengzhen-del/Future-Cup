import sqlite3, os
db_path = os.path.join(os.path.dirname(__file__), "..", "data", "inspect.db")
db_path = os.path.abspath(db_path)
if not os.path.exists(db_path):
    print("DB NOT FOUND at", db_path)
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t[0] for t in cur.fetchall()]
    print("=== 已有表 ===")
    for t in tables:
        cur.execute(f"SELECT count(*) FROM [{t}]")
        cnt = cur.fetchone()[0]
        cur.execute(f"PRAGMA table_info([{t}])")
        cols = [r[1] for r in cur.fetchall()]
        print(f"  {t}: {cnt} 条, 列={cols}")

    memory_kw = ['session','convers','history','memory','context','dialog','thread','summary']
    memory_tables = [t for t in tables if any(kw in t.lower() for kw in memory_kw)]
    print(f"\n=== 记忆/上下文相关表: {memory_tables or '❌ NONE'} ===")
    conn.close()

# 再看 state_machine 里的 agent 循环：是单次 run_once 还是有多轮
print("\n=== Agent 循环能力检查 ===")
import inspect
from app.agent.state_machine import InspectAgent
methods = [m for m in dir(InspectAgent) if not m.startswith('_') and callable(getattr(InspectAgent, m))]
print("InspectAgent 公开方法:", methods)
