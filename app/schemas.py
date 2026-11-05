"""数据契约：这里的字段必须和端侧 ets/model/ 一一对应，改字段先改这里。

字段全链路 camelCase；DB 列名、JSON key、ArkTS 字段三者同名。改字段三步：本文件 → 主纲 §3/§7 → 端侧 ets/model/。
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

Level = Literal["正常", "关注", "异常", "紧急"]
StepStatus = Literal["pending", "running", "done", "failed"]


class SensorSample(BaseModel):
    temperature: Optional[float] = None   # ℃
    humidity: Optional[float] = None      # %RH
    noise: Optional[float] = None         # dB
    simulated: bool = False               # 板子无传感器时为 True，报告里要写明


class InspectReq(BaseModel):
    taskId: str = ""
    deviceId: str = ""
    deviceName: str = ""
    deviceType: str = ""                   # 视觉分派依据：低压配电柜|高压柜|干式变压器|直流屏|电缆沟|消防器材
    voiceText: str = ""
    location: str = ""
    operator: str = ""                     # 巡检人
    capturedAt: str = ""                   # 端侧采集时刻（离线补传时还原时间）
    sensor: Optional[SensorSample] = None
    # 快速模式（single，一次综合判读，快）vs 详细模式（multi，四工具精细判读，慢但准）
    mode: Literal["quick", "detailed"] = "quick"
    # 反问补答：端侧收到 followUpQuestions 后用户回答填在这里（第二轮）
    clarifications: Optional[dict] = None  # {"q1":"...","q2":"..."} 或 {"answers": ["...", "..."]}


class StepOut(BaseModel):
    name: str
    status: StepStatus
    detail: str = ""
    durationMs: int = 0
    # 嵌套子步骤：每个子行是一条中间过程（如"调用 Qwen-VL…"、"提取到仪表读数 78.5℃"）
    # level 1=主步骤, 2=子行(缩进), 3=细节行(再缩进)
    subSteps: list[dict] = []  # [{"text":"…","level":2,"status":"info|ok|warn|fail"}]


class Finding(BaseModel):
    item: str          # 检查项：如 "母线接头温度"
    value: str         # 观测值：如 "78℃"
    abnormal: bool
    basis: str = ""    # 依据：视觉判读/台账比对/手册检索/传感器/语音描述·未经视觉确认


# ---- 语音结构化槽位（主纲 §3.5.3） ----
class VoiceSlotReading(BaseModel):
    item: str = ""
    value: str = ""
    unit: str = ""
    approx: bool = False                   # 口述估算值，不当真值


class VoiceSlots(BaseModel):
    parts: list[str] = []                  # 部位
    phenomena: list[str] = []              # 现象（标准词）
    readings: list[VoiceSlotReading] = []  # 口述读数
    sensory: list[str] = []                # 感官来源
    actions: list[str] = []                # 已做/待做动作


class VoiceOut(BaseModel):
    rawText: str = ""
    slots: VoiceSlots = Field(default_factory=VoiceSlots)
    negatives: list[str] = []              # 阴性证据（"没有异响"）
    severity: str = "未提及"               # 轻微|明显|严重|未提及
    confidence: float = 0.0


# ---- 视觉原始输出（主纲 §3.5.2） ----
class Indicator(BaseModel):
    kind: str = ""        # 数显表|指针表|指示灯|压力表
    name: str = ""
    value: str = ""
    abnormal: bool = False
    reason: str = ""


class Defect(BaseModel):
    type: str = ""        # 放电痕迹|破损|锈蚀|积尘|渗水|焦痕|异物|线缆裸露
    detail: str = ""
    abnormal: bool = True


class VisionOut(BaseModel):
    scene: str = ""
    readable: bool = True                  # 过曝/全黑/模糊 -> false，整轮转人工
    indicators: list[Indicator] = []
    defects: list[Defect] = []
    environment: dict = {}                 # 积水/杂物/通道堵塞/照明不足 -> bool
    unreadable: list[str] = []             # 看不清的绝不臆造
    riskHint: str = ""


class InspectResp(BaseModel):
    sessionId: str
    inspectionId: str = ""                 # 落库 ID，端侧本地回写关联
    imageUrl: str = ""                     # /media/xxx.jpg，报告页拼基址展示
    level: Level
    confidence: float = Field(ge=0.0, le=1.0)
    advice: str
    findings: list[Finding] = []
    voiceSlots: VoiceOut = Field(default_factory=VoiceOut)
    vision: VisionOut = Field(default_factory=VisionOut)
    steps: list[StepOut] = []
    workOrderId: Optional[str] = None
    needHuman: bool = False
    mock: bool = False
    durationMs: int = 0
    # 反问：当信息不全时，Agent 追问这些问题，端侧弹 Dialog 让用户补答
    followUpQuestions: list[str] = []
    # 档案完善标记：哪些字段是不完整的（visual_unreadable / voice_missing / sensor_missing / ...）
    incompleteFields: list[str] = []
    # 🧠 命中的历史巡检记忆（让端侧/HTTP 模式也能展示"我记得上次..."）
    memories: list[dict] = []


class TaskItem(BaseModel):
    id: str
    deviceId: str = ""
    title: str
    deviceName: str
    location: str
    status: Literal["待巡检", "进行中", "已完成"]
    priority: Literal["高", "中", "低"] = "中"
    deadline: str = ""
    assignee: str = "运维班组A"
    # 🟢 P0-1: 检查项模板（端侧按此顺序逐项确认，不再自维护）
    checklist: list[dict] = []
    checklistTotal: int = 0
    checklistDone: int = 0
    inspectionId: str = ""
    # 🟢 P0-2: 同一 assignee 当前唯一进行中任务为 true
    isCurrent: bool = False


class ChecklistItem(BaseModel):
    key: str
    name: str
    required: bool = True
    status: Literal["pending", "done", "skipped"] = "pending"


class DeviceChecklist(BaseModel):
    deviceType: str
    items: list[ChecklistItem] = []


class LoginReq(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    userId: str
    name: str
    role: str = "inspector"
    team: str = ""


class TokenPair(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "Bearer"
    expiresIn: int = 7200
    user: UserInfo


class DeviceProfile(BaseModel):
    id: str
    name: str = ""
    type: str = ""
    location: str = ""
    ratedTemp: Optional[float] = None
    ratedHumidity: Optional[float] = None
    installDate: str = ""
    lastInspectAt: str = ""
    history: str = ""
    qrCode: str = ""


class WorkOrder(BaseModel):
    id: str
    inspectionId: str = ""
    taskId: str = ""
    deviceId: str = ""
    deviceName: str = ""
    level: Level = "关注"
    description: str = ""
    assignee: str = "运维班组A"
    status: Literal["待处理", "处理中", "已闭环"] = "待处理"
    handleNote: str = ""
    createdAt: str = ""
    closedAt: str = ""


class ServerConfig(BaseModel):
    confidenceThreshold: float = 0.60
    wsEnabled: bool = True
    maxImageMb: int = 10
    mock: bool = False
    llm: bool = False
    vision: bool = False
    serverTime: str = ""