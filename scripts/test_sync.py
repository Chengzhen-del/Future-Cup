import sys; sys.path.insert(0, r"D:\code\inspectagent-cloud")
from app.main import app
import sqlite3
from pathlib import Path

# 查 DB_PATH
from app.config import settings
print(f"DB_PATH={settings.DB_PATH}")
print(f"exists={settings.DB_PATH.exists()}")

# 直接测 sync_snapshot 逻辑
conn = sqlite3.connect(str(settings.DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM inspections ORDER BY capturedAt DESC LIMIT 3").fetchall()
for r in rows:
    print(dict(r))
conn.close()
