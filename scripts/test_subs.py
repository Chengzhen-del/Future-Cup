import asyncio
from app.agent.state_machine import run_once
from app.schemas import InspectReq

req = InspectReq(
    taskId='T-1', deviceId='D-3001', deviceName='3号低压配电柜',
    deviceType='低压配电柜', voiceText='接头有点烫，闻到轻微焦味',
    location='A区配电房', operator='运维员A', capturedAt='2026-11-04 12:00:00',
    sensor={'temperature': 78.5, 'humidity': 62, 'simulated': True}, mode='quick'
)

async def t():
    r = await run_once(req)
    for s in r.steps:
        print(f"[{s.name}] subs={len(s.subSteps)} 条")
        for sub in s.subSteps[:3]:
            text = sub["text"][:60]
            print(f"  L{sub['level']} {sub['status']} {text}")
    print(f"final: level={r.level} followUp={r.followUpQuestions}")

asyncio.run(t())
