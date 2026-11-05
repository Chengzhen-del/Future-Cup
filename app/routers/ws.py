"""WebSocket：把 Agent 每一步实时推给端侧，做任务流卡片 + 打字机。

端侧发：{"type":"start","taskId":"","deviceId":"","deviceName":"",
         "voiceText":"","location":"","sensor":{...},"imageBase64":""}
服务端推：{"type":"step","step":{...}} / {"type":"token","text":"..."} / {"type":"final","data":{...}}
"""
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.state_machine import InspectAgent
from app.config import settings
from app.schemas import InspectReq
from app.services import store

router = APIRouter(tags=["agent"])
log = logging.getLogger("inspectagent.ws")


def _media_base(ws: WebSocket) -> str:
    """P1-10：WS 里图片绝对地址的基址（ws:// -> http://）。"""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    return (str(ws.base_url).rstrip("/")
            .replace("ws://", "http://").replace("wss://", "https://"))


@router.websocket("/ws/agent/{session_id}")
async def agent_ws(ws: WebSocket, session_id: str):
    await ws.accept()
    if settings.AUTH_ENABLED:
        info = store.verify_token(ws.query_params.get("token", ""))
        if not info:
            await ws.send_json({"type": "error", "code": "UNAUTHORIZED",
                                "message": "token 无效，请先登录再连 WS"})
            await ws.close(code=4401)
            return
    log.info("WS 连接建立: %s", session_id)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:  # noqa: BLE001
                await ws.send_json({"type": "error", "message": "非法 JSON"})
                continue

            if msg.get("type") != "start":
                await ws.send_json({"type": "error", "message": "首个消息必须是 start"})
                continue

            body = msg.get("payload", msg)
            req = InspectReq(
                taskId=body.get("taskId", ""),
                deviceId=body.get("deviceId", ""),
                deviceName=body.get("deviceName", ""),
                deviceType=body.get("deviceType", ""),
                voiceText=body.get("voiceText", ""),
                location=body.get("location", ""),
                operator=body.get("operator", ""),
                capturedAt=body.get("capturedAt", ""),
                sensor=body.get("sensor"),
                mode=body.get("mode", "quick"),
                clarifications=body.get("clarifications"),
            )
            img_b64 = body.get("imageBase64", "")
            image_bytes = base64.b64decode(img_b64) if img_b64 else b""
            rid = (body.get("requestId") or "").strip()

            # 幂等：同一 requestId 重复连 WS 时直接回放已有结果
            if rid:
                existed = store.get_inspection_by_request_id(rid)
                if existed:
                    tok = ws.query_params.get("token", "")
                    data = store.inspection_to_resp(
                        existed, _media_base(ws), tok).model_dump()
                    data["duplicate"] = True
                    await ws.send_json({"type": "final", "data": data})
                    await ws.send_json({"type": "end"})
                    continue

            agent = InspectAgent(req, image_bytes, rid)
            tok = ws.query_params.get("token", "")
            async for ev in agent.run():
                # P1-10/v8：WS final 始终重算图片/缩略图绝对地址（确保带 token）
                if ev.get("type") == "final":
                    d = ev.setdefault("data", {})
                    d["imageAbsoluteUrl"] = store.absolute_media_url(
                        d.get("imageUrl", ""), _media_base(ws), tok)
                    d["imageThumbAbsoluteUrl"] = store.absolute_media_url(
                        d.get("imageThumbUrl", ""), _media_base(ws), tok)
                await ws.send_json(ev)
            await ws.send_json({"type": "end"})
    except WebSocketDisconnect:
        log.info("WS 断开: %s", session_id)
    except Exception as e:  # noqa: BLE001
        log.exception("WS 异常: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
