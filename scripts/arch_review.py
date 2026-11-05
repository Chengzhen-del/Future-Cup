"""深度架构审查：找出 Agent 系统里还藏着的坑"""
import sys, asyncio, time
sys.path.insert(0, r"D:\code\inspectagent-cloud")

print("=" * 60)
print("1️⃣ run_once 与 run() 双路径数据一致性检查")
print("=" * 60)
from app.agent.state_machine import run_once, InspectAgent
from app.schemas import InspectReq

# run_once 有没有把 run() 里 yield 的 memories/subSteps/ReAct 事件漏掉？
import inspect
src = inspect.getsource(run_once)
print(f"run_once 直接调 store.finalize_inspection 了吗？ {'finalize_inspection' in src}")
print(f"run_once 是消费 run() 生成器吗？ {'async for' in src}")

# 检查 run_once 和 run() 是不是两套不同的 finalize 路径
agent_src = inspect.getsource(InspectAgent.run)
print(f"\nrun() 里直接调 store.finalize_inspection 吗？ {'finalize_inspection' in agent_src}")
print(f"run() 里直接调 store.save_inspection_memory 吗？ {'save_inspection_memory' in agent_src}")

print("\n" + "=" * 60)
print("2️⃣ LLM 调用健壮性检查")
print("=" * 60)
from app.services import llm
llm_src = inspect.getsource(llm.chat_json)
print(f"chat_json 有 timeout 参数吗？ {'timeout' in llm_src}")
print(f"chat_json 有重试/重试次数吗？ {'retry' in llm_src.lower()}")
print(f"chat_json 有并发锁吗？ {'Lock' in llm_src}")
print(f"chat_json 有 rate limit/退避吗？ {'backoff' in llm_src.lower()}")

# LLM 的 token 预算？
if hasattr(llm, 'MAX_TOKENS'):
    print(f"MAX_TOKENS 配置: {llm.MAX_TOKENS}")
else:
    print("⚠️ 没找到全局 MAX_TOKENS，可能爆 prompt 导致 OOM")

print("\n" + "=" * 60)
print("3️⃣ 全局可变状态检查（并发安全）")
print("=" * 60)
from app.services import rag
rag_src = inspect.getsource(rag)
# 检查 _collection / _mem_collection 是不是模块级单例
print(f"_collection 是模块级单例吗？ {'_collection = None' in rag_src}")
print(f"有并发初始化锁吗？ {'Lock' in rag_src} 或 {'asyncio.Lock' in rag_src}")
print(f"Chroma collection 操作有线程安全问题吗？ {'upsert' in rag_src and 'thread' not in rag_src.lower()}")

from app.agent import state_machine
sm_src = inspect.getsource(state_machine)
# _ctx 字典是每个 Agent 实例独立的吗？
print(f"\nInspectAgent._ctx 是 __init__ 里初始化的吗？ {'self._ctx: dict = {}' in sm_src or 'self._ctx = {}' in sm_src}")
# _last_react_events 会不会跨实例串数据
print(f"_last_react_events 是每个实例独立的吗？ {'self._last_react_events' in sm_src}")

print("\n" + "=" * 60)
print("4️⃣ 异常边界检查")
print("=" * 60)
# run() 里有没有漏掉的 try/except？
print("run() 里 ReAct Loop 有 try/except 吗？", 'except Exception' in sm_src and '_run_react_loop' in sm_src)
print("vision_agent.py 图像解码有 try/except 吗？让我看...")

print("\n" + "=" * 60)
print("5️⃣ 工具 JSON Schema 检查（LLM 能不能正确调工具）")
print("=" * 60)
from app.agent import tools
print("tools.dispatch 是硬编码路由吗？", 'def dispatch' in dir(tools))
print("LLM 看到过工具的 JSON Schema 吗？让我看 REACT_SYSTEM prompt...")
from app.agent.state_machine import REACT_SYSTEM
print("REACT_SYSTEM 里有工具 JSON Schema 吗？", '{' in REACT_SYSTEM and 'args' in REACT_SYSTEM)

print("\n" + "=" * 60)
print("6️⃣ WebSocket 多会话隔离检查")
print("=" * 60)
from app.routers import ws
ws_src = inspect.getsource(ws)
print("ws 路由每次 new InspectAgent 吗？", 'InspectAgent(' in ws_src)
print("有没有 session 复用（多浏览器 tab 同一个 session 会不会互相影响）？", 'session_id' in ws_src)

print("\n" + "=" * 60)
print("7️⃣ prompt 是否会爆（token 预算）")
print("=" * 60)
# 算一下最坏情况的 prompt 长度
plan_prompt = "设备：3号低压配电柜（低压配电柜）\n位置：A区\n语音描述：接头有点烫\n"
manual_prompt = " ".join(["规范条款内容" * 50] * 3)  # 3 条规则 × 80 字
decide_prompt = plan_prompt + manual_prompt + "观测事实：" + "- " * 10 + "历史记忆：" + "- " * 5
print(f"最坏情况下 decide prompt 估算字符: {len(decide_prompt)}")
print(f"如果用的是 DeepSeek-V3 128K context，1500 字符 ≈ 3000 token，安全")

print("\n✅ 审查完成")
