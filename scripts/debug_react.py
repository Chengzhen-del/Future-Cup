import asyncio
from app.agent.state_machine import InspectAgent
from app.schemas import InspectReq

async def t():
    req = InspectReq(taskId='T-DBG', deviceId='D-3001', deviceName='3号低压配电柜',
        deviceType='低压配电柜', voiceText='接头有点烫，温度很高',
        location='A区', operator='A', capturedAt='2026-11-06 16:00:00',
        sensor={'temperature':78.5,'humidity':60,'simulated':True}, mode='quick')
    agent = InspectAgent(req)
    events_seen = []
    async for ev in agent.run():
        if ev.get('type') in ('sub_step', 'memory_hit'):
            events_seen.append(ev)
        if ev.get('type') == 'final':
            break
    print(f"=== ReAct 调试 ===")
    print(f"_last_react_events 长度: {len(agent._last_react_events)}")
    for e in agent._last_react_events:
        print(f"  {e}")
    print(f"sub_step 事件数: {len([e for e in events_seen if e['type'] == 'sub_step'])}")
    for e in events_seen:
        if e['type'] == 'sub_step' and '🧠' in e.get('subStep', {}).get('text', ''):
            print(f"  ReAct sub_step: {e['subStep']['text'][:80]}")
        if e['type'] == 'memory_hit':
            print(f"  memory_hit: {len(e['memories'])} 条")

asyncio.run(t())
