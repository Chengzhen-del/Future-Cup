import asyncio
from app.agent.state_machine import run_once
from app.schemas import InspectReq

async def t():
    # 第三次巡检：同一设备，DB 里已有 2 条历史，应该能命中
    req = InspectReq(taskId='T-M3', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='今天再来测一下温度',
        location='A区', operator='A', capturedAt='2026-11-05 10:00:00',
        sensor={'temperature':74.0,'humidity':58,'simulated':True}, mode='quick')
    r = await run_once(req)
    print(f"=== 第三次巡检 ===")
    print(f"  level={r.level} conf={r.confidence}")
    for s in r.steps:
        if s.name == '任务规划' and s.subSteps:
            hits = [sub['text'][:60] for sub in s.subSteps if '🔍' in sub['text'] or '→' in sub['text']]
            print(f"  记忆命中相关 subSteps:")
            for h in hits:
                print(f"    {h}")
        if s.name == '档案完善' and s.subSteps:
            print(f"  档案完善: {[sub['text'][:60] for sub in s.subSteps]}")

asyncio.run(t())
