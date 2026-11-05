"""任务、设备、工单与系统配置接口。"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.schemas import DeviceChecklist, DeviceProfile, ServerConfig, TaskItem
from app.services import store

router = APIRouter(tags=["tasks"])


class TaskStatusPatch(BaseModel):
    status: str = ""
    inspectionId: str = ""


class WorkOrderPatch(BaseModel):
    status: str = ""
    handleNote: str = ""


TASK_STATUSES = {"待巡检", "进行中", "已完成"}
WO_STATUSES = {"待处理", "处理中", "已闭环"}


@router.get("/config", response_model=ServerConfig, summary="拉取阈值/开关")
def config():
    return ServerConfig(confidenceThreshold=settings.CONFIDENCE_THRESHOLD,
                        wsEnabled=True, maxImageMb=10,
                        mock=settings.mock_mode, llm=settings.has_llm,
                        vision=settings.has_vision,
                        serverTime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@router.get("/tasks", summary="巡检任务列表（可选分页/筛选）")
def tasks(page: int | None = None, pageSize: int = 20,
          status: str = "", deviceId: str = ""):
    """不传 page 返回数组（旧客户端兼容）；传 page 返回 {items,total,page,pageSize}。"""
    return store.paginate(store.list_tasks(status, deviceId), page, pageSize)


@router.get("/tasks/{task_id}", response_model=TaskItem, summary="任务详情")
def task_detail(task_id: str):
    t = store.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


@router.patch("/tasks/{task_id}/status", response_model=TaskItem, summary="改任务状态")
def task_status(task_id: str, body: TaskStatusPatch):
    if body.status not in TASK_STATUSES:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR",
            "message": f"status 只能是 {'/'.join(sorted(TASK_STATUSES))}"})
    t = store.update_task_status(task_id, body.status, body.inspectionId)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


@router.get("/device-types", summary="设备类型与检查项模板")
def device_types():
    return [{"deviceType": t, "items": store._default_checklist(t)}
            for t in store.CHECKLIST_TEMPLATES]


@router.get("/device-types/{device_type}/checklist", response_model=DeviceChecklist,
            summary="检查项模板（按设备类型）")
def device_type_checklist(device_type: str):
    if device_type not in store.CHECKLIST_TEMPLATES:
        raise HTTPException(status_code=404, detail="未知设备类型")
    return DeviceChecklist(deviceType=device_type,
                           items=store._default_checklist(device_type))


@router.get("/devices", summary="设备台账列表（可选分页/筛选）")
def devices(page: int | None = None, pageSize: int = 20, type: str = ""):
    return store.paginate(store.list_devices(type), page, pageSize)


@router.get("/devices/{device_id}", response_model=DeviceProfile, summary="设备档案")
def device(device_id: str):
    return store.get_device_profile(device_id)


@router.get("/workorders", summary="工单列表（可选分页/筛选）")
def workorders(page: int | None = None, pageSize: int = 20,
               status: str = "", level: str = "", deviceId: str = ""):
    return store.paginate(store.list_workorders(status, level, deviceId), page, pageSize)


@router.get("/workorders/{wo_id}", summary="工单详情")
def workorder_detail(wo_id: str):
    wo = store.get_workorder(wo_id)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    return wo


@router.patch("/workorders/{wo_id}/status", summary="工单流转（处理中/已闭环）")
def workorder_status(wo_id: str, body: WorkOrderPatch):
    if body.status not in WO_STATUSES:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR",
            "message": f"status 只能是 {'/'.join(sorted(WO_STATUSES))}"})
    cur = store.get_workorder(wo_id)
    if cur and cur.status == "已闭环" and body.status != "已闭环":
        raise HTTPException(status_code=409, detail={
            "code": "CONFLICT",
            "message": "工单已闭环，不可回退"})
    wo = store.update_workorder_status(wo_id, body.status, body.handleNote)
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    return wo