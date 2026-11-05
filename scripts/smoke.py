"""端到端冒烟：HTTP 上报 + WebSocket 任务流。

用法（服务已启动）：
    python scripts\smoke.py
"""
import asyncio
import base64
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from testimg import make_test_image  # noqa: E402

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws/agent/smoke-001"

PAYLOAD = {
    "taskId": "T-1001",
    "deviceId": "D-3001",
    "deviceName": "3号低压配电柜",
    "deviceType": "低压配电柜",
    "voiceText": "接头有点烫，闻到轻微焦味",
    "location": "A区配电房",
    "operator": "张三",
    "capturedAt": "2026-11-03 10:00:00",
    "sensor": {"temperature": 78.5, "humidity": 62, "noise": 55, "simulated": False},
}

# 自带一张测试配电柜图，让「视觉判读」这一步真的跑模型（不传图会降级跳过）
IMAGE_BYTES = make_test_image()
IMAGE_B64 = base64.b64encode(IMAGE_BYTES).decode()


def http_post(url: str, data: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def http_upload(url: str, payload: dict, image: bytes) -> dict:
    """multipart 上传：image 文件 + payload 表单（端侧真实调用方式）。"""
    boundary = "----smokeBoundary9x"
    body = b""
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload"\r\n\r\n'.encode()
        + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        + b"\r\n"
    )
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
        f'filename="cabinet.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
        + image
        + b"\r\n"
    )
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


async def ws_test() -> None:
    import websockets
    steps, tokens, final = [], [], None
    # ping 放宽：端侧心跳通常几十秒一次，别让测试客户端比真机还急
    async with websockets.connect(WS, open_timeout=30,
                                  ping_interval=30, ping_timeout=120) as ws:
        start = {"type": "start", "payload": {**PAYLOAD, "imageBase64": IMAGE_B64}}
        await ws.send(json.dumps(start))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            t = msg.get("type")
            if t == "step":
                s = msg["step"]
                steps.append(f"{s['name']}[{s['status']}]")
            elif t == "token":
                tokens.append(msg["text"])
            elif t == "final":
                final = msg["data"]
            elif t in ("end", "error"):
                break
    print("\n[WS] 步骤流： " + " → ".join(steps))
    print(f"[WS] 打字机： {''.join(tokens)[:40]}…（{len(tokens)} 字）")
    if final:
        print(f"[WS] 结论： level={final['level']} conf={final['confidence']} "
              f"needHuman={final['needHuman']} mock={final['mock']}")
        print(f"[WS] 证据： {len(final['findings'])} 条 ｜ 工单：{final['workOrderId']}")
    else:
        print("[WS] 未收到 final")


def check_server() -> None:
    """服务没起时给一句人话，别甩一屏 ConnectionRefused。"""
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=5):
            return
    except Exception:  # noqa: BLE001
        print("✗ 连不上 127.0.0.1:8000 —— 服务没启动。")
        print("  另开一个终端执行：")
        print("    cd D:\\code\\inspectagent-cloud")
        print("    .\\.venv\\Scripts\\Activate.ps1")
        print("    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(2)


def main() -> int:
    print("=" * 56)
    check_server()
    r = http_upload(f"{BASE}/api/v1/inspections/upload", PAYLOAD, IMAGE_BYTES)
    print("[HTTP] level =", r["level"], "| confidence =", r["confidence"], "| mock =", r["mock"])
    print("[HTTP] advice =", r["advice"][:50])
    print("[HTTP] 步骤 =", " → ".join(s["name"] + "[" + s["status"] + "]" for s in r["steps"]))
    print("[HTTP] 证据 =", len(r["findings"]), "条 ｜ 工单 =", r["workOrderId"])
    print("[HTTP] 落库 =", r.get("inspectionId", "") or "(未落库)", "| 图 =", r.get("imageUrl", "") or "(无)")
    for f in r["findings"][:5]:
        print(f"        · [{f.get('basis', '')}] {f.get('item', '')}："
              f"{str(f.get('value', ''))[:36]}")
    vs = r.get("voiceSlots", {})
    print("[HTTP] 语音槽位 =", vs.get("severity", ""), "| 阴性 =", vs.get("negatives", []))
    print("[HTTP] 视觉 =", r.get("vision", {}).get("scene", "")[:30] or "(空)")
    asyncio.run(ws_test())
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
