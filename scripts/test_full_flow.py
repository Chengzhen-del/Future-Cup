"""全流程实测：真实巡检（带图 multipart）→ ReAct 原生 Function Calling → token 统计落库 → 归档链路。

用法：先启动 uvicorn，再跑 python scripts/test_full_flow.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])
from scripts.testimg import make_test_image  # noqa: E402

BASE = "http://127.0.0.1:8000"
BOUNDARY = "----fullflowtestboundary"


def post_upload() -> dict:
    """multipart 上传巡检（含图），走完整 Agent 管线。
    端点签名：image=UploadFile, payload=JSON 字符串（InspectReq）。"""
    payload = json.dumps({
        "deviceId": "D-3001",
        "deviceName": "1号低压配电柜",
        "deviceType": "低压配电柜",
        "location": "配电房A区",
        "voiceText": "A相母线接头红外测温85度，闻到轻微焦味，指示灯正常",
        "mode": "detailed",
    }, ensure_ascii=False)
    img = make_test_image()
    body = bytearray()
    body += f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"payload\"\r\n\r\n{payload}\r\n".encode()
    body += f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"cab.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
    body += img
    body += f"\r\n--{BOUNDARY}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE}/api/v1/inspections/upload", data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    print("=" * 60)
    print("1. 提交真实巡检（multipart 带图 + 语音描述，detailed 模式）")
    print("=" * 60)
    t0 = time.time()
    resp = post_upload()
    dt = time.time() - t0
    print(f"   耗时 {dt:.1f}s")
    print(f"   level={resp.get('level')}  confidence={resp.get('confidence')}")
    print(f"   summary={resp.get('summary', '')[:80]}")
    print(f"   findings={len(resp.get('findings', []))} 条")
    print(f"   followUpQuestions={resp.get('followUpQuestions')}")
    print(f"   memories 命中={len(resp.get('memories', []))} 条")
    for st in resp.get("steps", []):
        subs = st.get("subSteps", [])
        print(f"   [{st.get('name')}] {st.get('status')}  (+{len(subs)} 思考细节)")
    insp_id = resp.get("id") or resp.get("inspectionId")
    print(f"   inspectionId={insp_id}")

    print("\n" + "=" * 60)
    print("2. Token 用量统计（/api/v1/stats/tokens）")
    print("=" * 60)
    stats = get("/api/v1/stats/tokens?days=7")
    t = stats["total"]
    print(f"   总调用 {t['calls']} 次 | prompt={t['promptTokens']} completion={t['completionTokens']} 总={t['totalTokens']} tokens | 成本 ¥{t['costCny']}")
    for c in stats["byCaller"]:
        print(f"   caller={c['caller']:<10} tokens={c['tokens']:<7} calls={c['calls']}  ¥{round(c['cost'], 4)}")
    for m in stats["byModel"]:
        print(f"   model={m['model']:<24} tokens={m['tokens']}")

    print("\n" + "=" * 60)
    print("3. 归档链路（inspections → findings / memories / traces）")
    print("=" * 60)
    detail = get(f"/api/v1/inspections/{insp_id}") if insp_id else {}
    print(f"   inspection 详情: level={detail.get('level')} findings={len(detail.get('findings', []))}")
    traces = get("/api/v1/traces?limit=3")
    tl = traces.get("traces", traces) if isinstance(traces, dict) else traces
    print(f"   traces 最近 {len(tl)} 条: " + ", ".join(str(x.get('id', x.get('inspectionId', '?')))[:12] for x in tl[:3]))
    sync = get("/api/v1/sync/snapshot")
    print(f"   sync/snapshot: inspections={len(sync.get('inspections', []))} devices={len(sync.get('devices', []))} (HTTP 200 ✅)")

    print("\n" + "=" * 60)
    print("4. 告警（LLM 熔断/RAG 降级会写 alert_logs）")
    print("=" * 60)
    alerts = get("/api/v1/alerts?unresolved=false&limit=5")
    print(f"   最近 {len(alerts.get('alerts', []))} 条告警")
    print("\n✅ 全流程实测完成")


if __name__ == "__main__":
    main()
