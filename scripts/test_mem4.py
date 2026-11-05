import asyncio, sys
from app.agent.state_machine import InspectAgent
from app.schemas import InspectReq
from app.services import store

async def t():
    req = InspectReq(taskId='T-M4', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='再测一下',
        location='A区', operator='A', capturedAt='2026-11-05 11:00:00',
        sensor={'temperature':75.0,'humidity':58,'simulated':True}, mode='quick')
    agent = InspectAgent(req)
    # 直接调用 store.load_recent_memories 看返回什么
    mems = store.load_recent_memories('D-3001', 5)
    print(f"[store.load_recent_memories] 直接调用返回: {len(mems)} 条", flush=True)
    
    async for ev in agent.run():
        if ev.get('type') == 'sub_step' and '🔍' in str(ev.get('subStep', {}).get('text', '')):
            print(f"[MEMORY HIT] {ev['subStep']['text']}", flush=True)
        if ev.get('type') == 'memory_hit':
            print(f"[MEMORY_HIT EVENT] {len(ev['memories'])} 条", flush=True)
        if ev.get('type') == 'final':
            print(f"[FINAL] level={ev['data']['level']}", flush=True)

asyncio.run(t())
