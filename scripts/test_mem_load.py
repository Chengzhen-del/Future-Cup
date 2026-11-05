from app.services import store
mems = store.load_recent_memories('D-3001', 5)
print(f"命中 {len(mems)} 条历史记忆")
for m in mems:
    print(f"  [{m['id']}] {m['capturedAt']} {m['level']}: {m['summary'][:80]}")
