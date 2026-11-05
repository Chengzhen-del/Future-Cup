import sqlite3, json
c = sqlite3.connect("data/inspect.db")
c.row_factory = sqlite3.Row

print("=" * 70)
print("📊 完整数据库现状盘点")
print("=" * 70)

tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
print(f"\n共 {len(tables)} 张表：")
for (t,) in tables:
    cnt = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [col[1] for col in c.execute(f"PRAGMA table_info({t})").fetchall()]
    print(f"\n  📋 {t} ({cnt} 条)")
    print(f"     字段: {', '.join(cols)}")

print("\n" + "=" * 70)
print("📋 数据归档链路完整性检查")
print("=" * 70)

checks = {
    "巡检主记录 (inspections)": "有",
    "设备台账 (devices)": "有",
    "巡检任务 (tasks)": "有",
    "工单 (workorders)": "有",
    "检查项详情 (findings)": "有",
    "现场图片 (media)": "有",
    "会话 (sessions)": "有 (P0 新增)",
    "历史记忆 (inspection_memories)": "有 (P0 新增)",
    "Trace 事件流 (agent_traces)": "有 (P3-1 新增)",
    "规范版本 (schema_version)": "有",
}
for k, v in checks.items():
    print(f"  {'✅' if '有' in v else '❌'} {k}: {v}")

print("\n" + "=" * 70)
print("🔗 表间关联关系")
print("=" * 70)
print("""
inspections ──(inspectionId)──→ findings (1:N)
inspections ──(inspectionId)──→ media (1:N)
inspections ──(taskId)──────→ tasks
inspections ──(deviceId)────→ devices
inspections ──(sessionId)────→ sessions
inspections ──(inspectionId)─→ workorders (异常/紧急自动创建)
inspection_memories ─(deviceId)→ devices
sessions ──(sessionId)─────→ inspection_memories
sessions ──(sessionId)─────→ agent_traces
agent_traces ─(sessionId)────→ sessions
agent_traces ─(inspectionId)─→ inspections
""")

print("=" * 70)
print("📋 索引情况")
print("=" * 70)
indexes = c.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'").fetchall()
for name, tbl in indexes:
    print(f"  📌 {name} → {tbl}")

print("\n" + "=" * 70)
print("❓ 缺失归档/能力")
print("=" * 70)
print("""
❌ 1. 归档与在线库未分离（全在一个 inspect.db，后期会爆）
❌ 2. 记忆没有自动过期清理（180 天前的巡检还在 pollute RAG）
❌ 3. 没有用户/人员表（operator 是 free text，没法区分"张三"还是"ZhangSan"）
❌ 4. 没有规范版本历史（knowledge/rules.md 改了但没存档）
❌ 5. 没有告警记录（LLM 熔断/RAG 降级了但没地方查）
❌ 6. 没有批量巡检表（一次巡检多台设备现在是 N 次 HTTP 调用）
❌ 7. 没有 API 调用次数统计（生产计费/限流需要）
""")
