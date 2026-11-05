import asyncio
from app.agent.state_machine import run_once
from app.schemas import InspectReq

async def t():
    req = InspectReq(taskId='T-P2', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='接头有点烫，温度很高',
        location='A区', operator='A', capturedAt='2026-11-06 10:00:00',
        sensor={'temperature':78.5,'humidity':60,'simulated':True}, mode='quick')
    r = await run_once(req)
    print(f"=== ReAct 测试 ===")
    print(f"  level={r.level} conf={r.confidence} durationMs={r.durationMs}")
    # 看看步骤总数和定级决策的 subSteps
    print(f"  总步骤数: {len(r.steps)}")
    for s in r.steps:
        if s.name == '定级决策':
            print(f"  定级决策 subSteps ({len(s.subSteps)} 条):")
            for sub in s.subSteps:
                print(f"    {sub['text'][:80]}")
    print(f"  memories count={len(r.memories)}")

asyncio.run(t())
