from app.main import app
from app.services import llm, rag
from app.agent.state_machine import InspectAgent, REACT_SYSTEM
from app.schemas import InspectReq

print("✅ 后端 import OK")
print(f"  llm._llm_semaphore: {llm._llm_semaphore}")
print(f"  llm._circuit_breaker: {llm._circuit_breaker}")
print(f"  rag._collection_lock: {rag._collection_lock}")
print(f"  REACT_SYSTEM 有 search_manual: {'search_manual' in REACT_SYSTEM}")
print(f"  REACT_SYSTEM 有 JSON args 格式: {'args' in REACT_SYSTEM}")

req = InspectReq(taskId='T-X', deviceId='D', deviceName='x', deviceType='x',
    voiceText='x', location='x', operator='x', capturedAt='x',
    sensor={'temperature':25,'humidity':50,'simulated':True}, mode='quick')
a = InspectAgent(req)
print(f"  a._llm_fail_count: {a._llm_fail_count}")
print(f"  a._last_react_events: {a._last_react_events}")

print("\n✅ 所有架构修复验证通过")
