"""端侧数据同步 + Agent 架构完善性检查"""
import sys; sys.path.insert(0, r"D:\code\inspectagent-cloud")
from app.services import store
import sqlite3, json

print("=" * 70)
print("1️⃣ 端侧数据同步检查")
print("=" * 70)

# 检查现有 HTTP API 能不能支持端侧拉取
import inspect
from app import main
routes = [r.path for r in main.app.routes if hasattr(r, 'path')]
print(f"\n现有 API 路由数: {len(routes)}")
for r in sorted(routes):
    print(f"  {r}")

# 端侧需要的数据
print("""
端侧需要的同步能力：
  ✅ GET  /api/v1/devices         → 设备台账已可拉
  ✅ GET  /api/v1/tasks           → 任务列表已可拉
  ✅ GET  /api/v1/inspections     → 巡检记录已可拉
  ✅ GET  /api/v1/workorders      → 工单已可拉
  ✅ GET  /media/{file}           → 巡检现场图片已可拉
  ✅ WebSocket /ws/agent          → 实时巡检
  ❌ 没有批量同步 API（一次拉全量快照）
  ❌ 没有增量同步 API（since_timestamp=只拉变化的）
  ❌ 没有 conflict 解决策略（端侧和云端同时改了怎么办）
""")

print("=" * 70)
print("2️⃣ 知识库（RAG）现状")
print("=" * 70)
from app.services import rag
col = rag._get_mem_collection()
if col:
    cnt = col.count()
    print(f"✅ Chroma memory collection: {cnt} 条")
else:
    print("⚠️ Chroma 不可用，走关键词兜底")

# 规范语料
import os
rules_file = os.path.join(os.path.dirname(store.__file__), "..", "..", "knowledge", "rules.md")
if os.path.exists(rules_file):
    with open(rules_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"✅ 规范语料 knowledge/rules.md: {len(lines)} 行")
else:
    print(f"⚠️ rules.md 不存在于 {rules_file}")

print("""
可扩充方向：
  ❌ 现在只有一个 rules.md → 可以拆成 低压配电柜/变压器/开关柜/电缆 等分册
  ❌ 没有规范版本管理 → 加 version 字段到 rules.md 每条
  ❌ 没有设备手册 → 每台设备的操作手册 PDF/Markdown
  ❌ 没有历史案例库 → 把工单历史当案例进 RAG
  ❌ 没有故障树分析 → 知道"发热+焦味→可能原因A/B/C"
""")

print("=" * 70)
print("3️⃣ 工具调用（tools.py）现状")
print("=" * 70)
from app.agent import tools
print("tools.py 里已有的函数:")
for name in dir(tools):
    obj = getattr(tools, name)
    if callable(obj) and not name.startswith("_"):
        sig = inspect.signature(obj)
        print(f"  🛠 {name}{sig}")

print("""
可扩充方向：
  ❌ 现场补图请求工具（Agent 判断看不清让用户再拍一张）
  ❌ 实时数据查询工具（查传感器最新值，不是靠用户手填）
  ❌ 同类设备对比工具（"看看隔壁 B 区同型号设备温度如何"）
  ❌ 知识库追问工具（"这个规范的完整条款是什么"）
  ❌ 应急联系人工具（"这个设备该找谁处理"）
  ❌ 风险评估工具（"如果这个异常不处理，多久会出事"）
  ❌ 一键生成处置方案工具（"按规程给我列 123 步"）
  ❌ 工单分派工具（"自动派给张师傅"）
""")

print("=" * 70)
print("4️⃣ 端侧数据归档/本地库现状")
print("=" * 70)
print("""
端侧（ArkTS HarmonyOS）现状：
  ✅ HttpService 已封装所有云端 API
  ✅ WsService 已封装 WebSocket 实时流
  ✅ InspectModels 16 个数据接口已定义
  ❌ 端侧没有本地数据库（Room/SQLite）
  ❌ 没有离线巡检能力（网断了就不能巡检）
  ❌ 没有照片本地缓存（media/* 图片每次重新下载）
  ❌ 没有本地存储/同步策略
""")
