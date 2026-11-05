import sys; sys.path.insert(0, r"D:\code\inspectagent-cloud")
from app.services import store

print("list_devices:", store.list_devices()[:2])
print("list_tasks:", store.list_tasks()[:2])

# 看看 sync_snapshot 为什么 500
import sqlite3
conn = sqlite3.connect(str(store.DB_PATH))
conn.row_factory = sqlite3.Row
try:
    rows = conn.execute("SELECT * FROM inspections ORDER BY capturedAt DESC LIMIT 3").fetchall()
    print("inspections:", [dict(r) for r in rows])
except Exception as e:
    print(f"inspections error: {e}")
try:
    rows = conn.execute("SELECT * FROM workorders ORDER BY createdAt DESC LIMIT 3").fetchall()
    print("workorders:", [dict(r) for r in rows])
except Exception as e:
    print(f"workorders error: {e}")
conn.close()
