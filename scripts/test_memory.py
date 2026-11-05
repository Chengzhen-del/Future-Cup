import asyncio
from app.agent.state_machine import run_once
from app.schemas import InspectReq

async def t():
    req1 = InspectReq(taskId='T-M1', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='接头有点烫，闻到轻微焦味',
        location='A区', operator='A', capturedAt='2026-11-04 12:00:00',
        sensor={'temperature':78.5,'humidity':60,'simulated':True}, mode='quick')
    r1 = await run_once(req1)
    print(f"=== 第一次巡检 ===")
    print(f"  level={r1.level} conf={r1.confidence} inspectionId={r1.inspectionId}")

    req2 = InspectReq(taskId='T-M2', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='又来看一下，温度好像还是有点高',
        location='A区', operator='A', capturedAt='2026-11-04 15:00:00',
        sensor={'temperature':76.0,'humidity':61,'simulated':True}, mode='quick')
    r2 = await run_once(req2)
    print(f"=== 第二次巡检（同设备） ===")
    print(f"  level={r2.level} conf={r2.confidence}")
    print(f"  总步骤数: {len(r2.steps)}")
    for s in r2.steps:
        if s.name == '任务规划' and s.subSteps:
            subs = [sub['text'][:60] for sub in s.subSteps]
            print(f"  任务规划 subSteps: {subs}")
        if s.name == '档案完善' and s.subSteps:
            subs = [sub['text'][:60] for sub in s.subSteps]
            print(f"  档案完善 subSteps: {subs}")

asyncio.run(t())
