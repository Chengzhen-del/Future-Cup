"""巡检上报：图片 + 语音文本 + 传感器 -> Agent -> 定级结论并落库。

端侧用 multipart 提交（主链路）：
  image   = 图片文件（img 归 store.finalize_inspection 落盘 + 登记 media）
  audio   = 音频文件（初赛只留证、不转写，可省略）
  payload = JSON 字符串（对应 InspectReq）
"""
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agent.state_machine import run_once
from app.schemas import InspectReq, InspectResp
from app.services import store

router = APIRouter(tags=["inspections"])

MAX_IMAGE_MB = 10


@router.post("/inspections/upload", response_model=InspectResp,
             summary="上传巡检数据（推荐，multipart 带图）")
async def upload(image: UploadFile | None = File(None),
                 audio: UploadFile | None = File(None),
                 payload: str = Form("{}")):
    try:
        req = InspectReq(**json.loads(payload or "{}"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"payload 解析失败: {e}")

    image_bytes = b""
    if image is not None:
        image_bytes = await image.read()
        if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片超过 10MB")
    # audio：初赛「录音留证不转写」，此处接收不处理（媒体归档后续补）
    return await run_once(req, image_bytes)


@router.post("/inspections", response_model=InspectResp, summary="纯 JSON 上报（无图）")
async def create(req: InspectReq):
    return await run_once(req, b"")


@router.get("/inspections", summary="巡检记录列表")
def list_inspections(limit: int = 50):
    return store.list_inspections(limit)


@router.get("/inspections/{inspection_id}", summary="巡检详情（含 findings / steps）")
def get_inspection(inspection_id: str):
    d = store.get_inspection(inspection_id)
    if not d:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return d