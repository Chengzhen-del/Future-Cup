import asyncio, json, websockets

async def test():
    sid = 'test123456'
    uri = f'ws://127.0.0.1:8000/ws/agent/{sid}'
    print(f'连接 {uri}...')
    async with websockets.connect(uri) as ws:
        payload = {
            'type': 'start',
            'payload': {
                'taskId': 'T-1', 'deviceId': 'D-3001',
                'deviceName': '3号低压配电柜',
                'deviceType': '低压配电柜',
                'voiceText': '接头有点烫',
                'location': 'A区配电房',
                'operator': '运维员A',
                'capturedAt': '2026-11-04 12:00:00',
                'sensor': {'temperature': 78.5, 'humidity': 62, 'simulated': True},
                'mode': 'quick',
                'imageBase64': ''
            }
        }
        print('发送 start...')
        await ws.send(json.dumps(payload))
        i = 0
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            i += 1
            t = msg['type']
            if t == 'step':
                s = msg['step']
                print(f"  #{i} [step] {s['name']} -> {s['status']} ({s.get('durationMs',0)}ms)")
            elif t == 'token':
                print(f"  #{i} [token] {msg['text']}", end='', flush=True)
            elif t == 'final':
                r = msg['data']
                fu = r.get('followUpQuestions', [])
                print(f"\n  #{i} [final] level={r['level']} conf={r['confidence']} followUp={fu}")
            elif t == 'end':
                print(f"  #{i} [end] DONE")
                break
            elif t == 'error':
                print(f"  #{i} [error] {msg}")
                break

asyncio.run(test())
