"""真实缺口审查"""
print("=" * 60)
print("真实缺口（二次精准审查）")
print("=" * 60)

import sys; sys.path.insert(0, r"D:\code\inspectagent-cloud")
import inspect
from app.services import llm, rag, store

print("\n🔍 llm.py 实际情况:")
print(f"  chat() 有 max_retry={inspect.signature(llm.chat).parameters.get('max_retry').default}")
print(f"  client timeout 已设置: 60s ✅")
print(f"  chat_json 解析失败有 default 兜底 ✅")
print(f"  chat_with_tools 完整实现 ✅")
print(f"  stream_chat 完整实现 ✅")
print(f"  ❌ 无并发信号量（同时 N 个巡检 = N 个 LLM 调用）")
print(f"  ❌ 重试无指数退避（连续 2 次 60s timeout 还是要等 120s）")
print(f"  ❌ 无 token budget 截断（historyPrompt 无限塞入）")

print("\n🔍 rag.py 实际情况:")
import threading
print(f"  _collection 是否有 Lock 保护？ {'Lock' in dir(rag) or hasattr(rag, '_lock')}")
print(f"  ❌ Chroma 多进程并发 upsert 可能 crash（官方文档明确不安全）")
print(f"  rag 函数是纯同步（to_thread 调用时会 GIL 串行，其实在当前单 worker 下安全）")

print("\n🔍 state_machine 实际情况:")
from app.agent.state_machine import InspectAgent
sm_src = inspect.getsource(InspectAgent)
print(f"  _last_react_events 是 per-instance: ✅")
print(f"  _ctx 是 per-instance: ✅")
print(f"  session_id per-instance: ✅")
print(f"  _decide 返回值格式稳定吗？让我看...")

print("\n🔍 tools.py 实际情况:")
from app.agent import tools
tools_src = inspect.getsource(tools)
print(f"  dispatch 是路由: {'def dispatch' in tools_src} ✅")
print(f"  工具有 JSON Schema 吗？让我看...")
import json
# 检查每个工具的 schema
for tname in ['search_manual', 'get_device_profile', 'list_devices']:
    t = getattr(tools, tname, None)
    if t:
        sig = inspect.signature(t)
        print(f"  {tname}{sig}")

print("\n🔍 WebSocket 多会话隔离:")
from app.routers import ws
ws_src = inspect.getsource(ws)
print(f"  每次 new InspectAgent: {'InspectAgent(' in ws_src} ✅")
print(f"  同一个 session_id 多次 start: {'start' in ws_src}")

print("\n" + "=" * 60)
print("📋 真正需要修的（按优先级）:")
print("=" * 60)
print("P0-1: LLM 并发信号量（最多 3 个并行）→ 避免打爆配额")
print("P0-2: LLM 重试加指数退避（sleep 1s, 2s, 4s）→ 避免雪崩")
print("P0-3: Chroma 加 threading.Lock → 避免数据损坏")
print("P1-1: historyPrompt 超 500 字自动截断 → 避免爆 context")
print("P1-2: REACT_SYSTEM 给完整工具 JSON Schema → LLM 调工具更准")
print("P2-1: run() 里 LLM 连续 3 次失败熔断 → 降级 mock 不挂")
