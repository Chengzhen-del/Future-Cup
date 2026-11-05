"""视觉模型（豆包视觉，方舟 OpenAI 兼容，接入点 ep-xxxx）。

DeepSeek 不支持图像，视觉必须走这一路。
输入：图片 bytes + 语音提示 + 设备类型；输出：结构化 dict（VisionOut 结构，主纲 §3.5.2）。
代码里 model 填的是 ep- 接入点 ID（settings.QWEN_VL_MODEL），不是模型名。

多 Agent 化：视觉拆成 4 个聚焦工具（可读性评估 / 读表 / 缺陷识别 / 环境检查），
每个工具只做一次 VLM 调用、只输出自己负责的字段；analyze() 保留为编排器，对外结构不变。
"""
import base64
import json
import logging

from app.config import settings
from app.services.llm import _strip_fence

log = logging.getLogger("inspectagent.vision")

# 按设备类型分派检查项（主纲 §3.5.2）：让模型"带着问题看"
DEVICE_CHECKS = {
    "低压配电柜": "柜体外观、指示灯、数显/指针表、柜门锁闭、标识牌、柜前通道；可读数：温度数显、电流表、电压表",
    "高压柜": "分合闸指示、断路器状态、仪表、外观、闭锁；可读数：压力表、分合指示器",
    "干式变压器": "绕组温控仪、冷却风机、绝缘子、围栏、积尘；可读数：温控仪（℃）",
    "直流屏": "合母/控母电压数显、模块指示灯、电池组外观；可读数：电压表（V）",
    "电缆沟": "积水、盖板、防火封堵、电缆外皮、杂物；无可读数对象",
    "消防器材": "压力表指针（红/绿区）、检验合格证、筒体、取用通道；可读数：压力表",
}

DEFAULT_ENVIRONMENT = {"积水": False, "杂物": False, "通道堵塞": False, "照明不足": False}

# ---- 聚焦工具各自的 prompt：只输出自己那段 JSON，别的字段不要 ----
ASSESS_PROMPT = """你是电力配电房巡检专家。请判断这张现场照片是否可用于巡检判读，只输出 JSON，不要任何多余文字：
{
  "scene": "一句话描述场景",
  "readable": true,
  "unreadable": ["看不清的对象"],
  "riskHint": "整图风险提示一句话"
}
铁律：照片过曝、全黑、严重模糊时 readable 填 false；看不清的对象一律放进 unreadable 数组，绝不臆造。
只输出上面这段 JSON，不要输出其他任何字段。"""

METER_PROMPT = """你是电力配电房巡检专家。请从这张现场照片中读取仪表读数，只输出 JSON，不要任何多余文字：
{
  "indicators": [
    {"kind": "数显表|指针表|指示灯|压力表", "name": "仪表名称", "value": "读数(带单位)", "abnormal": true或false, "reason": "判断依据(如超过限值70℃)"}
  ]
}
铁律：只输出你能从图中确认的读数；看不清的仪表不要臆造数值，直接省略；没有任何可读仪表时 indicators 给空数组 []。
只输出上面这段 JSON，不要输出其他任何字段。"""

DEFECT_PROMPT = """你是电力配电房巡检专家。请从这张现场照片中识别外观缺陷，只输出 JSON，不要任何多余文字：
{
  "defects": [
    {"type": "放电痕迹|破损|锈蚀|积尘|渗水|焦痕|异物|线缆裸露", "detail": "具体描述", "abnormal": true}
  ]
}
铁律：只报告你能从图中确认的缺陷；没有任何缺陷时 defects 给空数组 []。
只输出上面这段 JSON，不要输出其他任何字段。"""

ENV_PROMPT = """你是电力配电房巡检专家。请检查这张现场照片中的环境隐患，只输出 JSON，不要任何多余文字：
{
  "environment": {"积水": false, "杂物": false, "通道堵塞": false, "照明不足": false}
}
铁律：没看到的项一律填 false 不要填 null。
只输出上面这段 JSON，不要输出其他任何字段。"""

COMBINED_PROMPT = """你是电力配电房巡检专家。请对这张现场照片做一次完整的巡检判读，只输出一个 JSON 对象，不要任何多余文字：
{
  "scene": "一句话描述场景",
  "readable": true,
  "unreadable": ["看不清的对象"],
  "riskHint": "整图风险提示一句话",
  "indicators": [
    {"kind": "数显表|指针表|指示灯|压力表", "name": "仪表名称", "value": "读数(带单位)", "abnormal": true或false, "reason": "判断依据"}
  ],
  "defects": [
    {"type": "放电痕迹|破损|锈蚀|积尘|渗水|焦痕|异物|线缆裸露", "detail": "具体描述", "abnormal": true}
  ],
  "environment": {"积水": false, "杂物": false, "通道堵塞": false, "照明不足": false}
}
铁律：①只输出你能从图中确认的内容，看不清的不要臆造；②没有可读仪表时 indicators 给空数组；③没有缺陷时 defects 给空数组；④环境项没看到的填 false 不要 null；⑤照片过曝/全黑/严重模糊时 readable 填 false，并把看不清的对象放入 unreadable。
只输出这段 JSON，不要输出其他任何字段。"""


def _sniff_mime(b: bytes) -> str:
    """按文件头判断真实图片类型。端侧拍的是 JPEG，脚本自造的测试图是 PNG，
    标错 MIME 会让部分视觉模型直接拒收。"""
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _call_vlm(image_bytes: bytes, prompt: str, device_type: str = "", hint: str = "") -> dict:
    """私有帮助：单次 VLM 调用 -> dict。任何异常返回空 dict 并 log，绝不抛。"""
    if not settings.has_vision or not image_bytes:
        return {}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.DASHSCOPE_API_KEY,
                        base_url=settings.DASHSCOPE_BASE_URL, timeout=90)
        b64 = base64.b64encode(image_bytes).decode()
        user_msg = prompt
        if device_type:
            check_hint = DEVICE_CHECKS.get(device_type, "设备外观、仪表、指示灯、环境")
            user_msg += f"\n本图设备类型：{device_type}，重点核对：{check_hint}"
        if hint:
            user_msg += f"\n现场语音提示（可指导你重点看哪里，但以图像为准）：{hint}"
        resp = client.chat.completions.create(
            model=settings.QWEN_VL_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{_sniff_mime(image_bytes)};base64,{b64}"}},
                {"type": "text", "text": user_msg},
            ]}],
            temperature=0.1,
        )
        try:
            from app.services.llm import _track_usage
            _track_usage(getattr(resp, "usage", None), "vision",
                         model=settings.QWEN_VL_MODEL)
        except Exception:  # noqa: BLE001
            pass
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(_strip_fence(raw))
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        log.warning("视觉模型调用失败: %s", e)
        return {}


def _as_str_list(v) -> list:
    return [str(x) for x in v] if isinstance(v, list) else []


def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def assess_readable(image_bytes: bytes) -> dict:
    """判断照片是否可用于巡检判读。返回 {scene, readable, unreadable, riskHint}。"""
    data = _call_vlm(image_bytes, ASSESS_PROMPT)
    if not data:
        return {"scene": "", "readable": False,
                "unreadable": ["整图（视觉模型不可用）"], "riskHint": ""}
    readable = data.get("readable", True)
    if not isinstance(readable, bool):
        readable = True
    return {
        "scene": str(data.get("scene", "")),
        "readable": readable,
        "unreadable": _as_str_list(data.get("unreadable")),
        "riskHint": str(data.get("riskHint", "")),
    }


def read_meter(image_bytes: bytes, hint: str = "", device_type: str = "") -> dict:
    """读取仪表读数。返回 {indicators: [{kind,name,value,abnormal,reason}]}。"""
    data = _call_vlm(image_bytes, METER_PROMPT, device_type, hint)
    indicators = data.get("indicators")
    return {"indicators": indicators if isinstance(indicators, list) else []}


def detect_defect(image_bytes: bytes, hint: str = "", device_type: str = "") -> dict:
    """识别外观缺陷。返回 {defects: [{type,detail,abnormal}]}。"""
    data = _call_vlm(image_bytes, DEFECT_PROMPT, device_type, hint)
    defects = data.get("defects")
    return {"defects": defects if isinstance(defects, list) else []}


def check_environment(image_bytes: bytes) -> dict:
    """检查环境隐患。返回 {environment: {积水/杂物/通道堵塞/照明不足 -> bool}}。"""
    data = _call_vlm(image_bytes, ENV_PROMPT)
    env = _as_dict(data.get("environment")) if data else {}
    return {"environment": {
        "积水": bool(env.get("积水", False)),
        "杂物": bool(env.get("杂物", False)),
        "通道堵塞": bool(env.get("通道堵塞", False)),
        "照明不足": bool(env.get("照明不足", False)),
    }}


def analyze_single(image_bytes: bytes, hint: str = "", device_type: str = "") -> dict:
    """单次综合判读（默认，快）：一次 VLM 调用返回完整 VisionOut 结构。"""
    default = {
        "scene": "", "readable": True, "indicators": [], "defects": [],
        "environment": dict(DEFAULT_ENVIRONMENT), "unreadable": [], "riskHint": "",
    }
    if not settings.has_vision or not image_bytes:
        default["readable"] = False
        return default
    data = _call_vlm(image_bytes, COMBINED_PROMPT, device_type, hint)
    if not data:
        default["readable"] = False
        default["unreadable"] = ["整图（视觉模型不可用）"]
        return default
    readable = data.get("readable", True)
    if not isinstance(readable, bool):
        readable = True
    env = _as_dict(data.get("environment"))
    indicators = data.get("indicators")
    defects = data.get("defects")
    return {
        "scene": str(data.get("scene", "")),
        "readable": readable,
        "indicators": indicators if isinstance(indicators, list) else [],
        "defects": defects if isinstance(defects, list) else [],
        "environment": {
            "积水": bool(env.get("积水", False)),
            "杂物": bool(env.get("杂物", False)),
            "通道堵塞": bool(env.get("通道堵塞", False)),
            "照明不足": bool(env.get("照明不足", False)),
        },
        "unreadable": _as_str_list(data.get("unreadable")),
        "riskHint": str(data.get("riskHint", "")),
    }


def analyze(image_bytes: bytes, hint: str = "", device_type: str = "") -> dict:
    """视觉编排入口：VISION_MODE=single（默认）走单次综合判读（快）；
    multi 走四工具精细判读（慢，多 Agent 演示用）。对外结果结构不变。"""
    if settings.VISION_MODE != "multi":
        return analyze_single(image_bytes, hint, device_type)

    default = {
        "scene": "", "readable": True, "indicators": [], "defects": [],
        "environment": dict(DEFAULT_ENVIRONMENT),
        "unreadable": [], "riskHint": "",
    }
    if not settings.has_vision or not image_bytes:
        default["readable"] = False
        default["unavailable"] = True
        return default

    assess = assess_readable(image_bytes)
    if not assess.get("readable"):
        default["readable"] = False
        default["scene"] = assess.get("scene", "")
        default["unreadable"] = assess.get("unreadable") or ["整图（不可读）"]
        default["riskHint"] = assess.get("riskHint", "")
        return default

    meters = read_meter(image_bytes, hint, device_type)
    defects = detect_defect(image_bytes, hint, device_type)
    env = check_environment(image_bytes)
    return {
        "scene": assess.get("scene", ""),
        "readable": True,
        "indicators": meters.get("indicators", []),
        "defects": defects.get("defects", []),
        "environment": env.get("environment", dict(DEFAULT_ENVIRONMENT)),
        "unreadable": assess.get("unreadable", []),
        "riskHint": assess.get("riskHint", ""),
    }