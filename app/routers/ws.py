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
            )
            img_b64 = body.get("imageBase64", "")
            image_bytes = base64.b64decode(img_b64) if img_b64 else b""

            agent = InspectAgent(req, image_bytes)
            async for ev in agent.run():
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
