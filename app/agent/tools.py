"""Agent 工具调用层（tool calling）。

把内部能力（检规检索、台账/任务查询、系统配置）以 OpenAI `tools` 格式暴露给大模型，
由 dispatch() 统一路由。原则：
1. 只描述工具 + 路由，不 new client、不直接调大模型
2. dispatch 永远返回 JSON 字符串，绝不把异常抛给上层（保证定级链路不断）
"""
import json
import logging

from app.config import settings
from app.services import rag, store

log = logging.getLogger("inspectagent.tools")

# ---- OpenAI tools（function calling）JSON schema ----
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_manual",
            "description": "检索配电房巡检规程/规范条款，用于补充定级依据。输入自然语言问题或关键词，返回相关的规范条目原文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的规范问题或关键词，例如「母线接头温度限值」「放电痕迹怎么定级」",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_profile",
            "description": "查询设备档案/台账：额定温度、额定湿度、安装日期、历史巡检记录等，用于比对是否超限或有无历史异常。",
            "parameters": {
                "type": "object",
                "properties": {
                    "deviceId": {
                        "type": "string",
                        "description": "设备编号，例如 D-3001",
                    },
                },
                "required": ["deviceId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task",
            "description": "查询巡检任务详情：任务标题、设备、位置、优先级、截止时间、指派人等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {
                        "type": "string",
                        "description": "任务编号，例如 T-1001",
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "列出全量设备清单（编号、名称、类型、位置、额定值等），用于跨设备比对或定位现场设备。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": "查询系统运行配置，例如定级置信度阈值、是否 mock 模式等。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "similar_devices",
            "description": "查询同类型其他设备的历史巡检情况，用于同类对比（例如看看隔壁 B 区同型号配电柜温度是否也高）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "deviceType": {
                        "type": "string",
                        "description": "设备类型，例如「低压配电柜」",
                    },
                    "excludeDeviceId": {
                        "type": "string",
                        "description": "要排除的设备编号（自己），例如 D-3001",
                    },
                },
                "required": ["deviceType"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contacts",
            "description": "查询设备/区域对应的应急联系人、责任人、维修班组信息，用于异常/紧急情况时派单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "deviceId": {
                        "type": "string",
                        "description": "设备编号，例如 D-3001",
                    },
                    "area": {
                        "type": "string",
                        "description": "区域名，例如「A区」",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_reshoot",
            "description": "请求巡检员重新拍摄现场照片（当视觉不可读/模糊/过曝时），返回中文提示文案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "为什么要重拍，例如「当前图像过曝看不清指针读数」",
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "怎么拍更好，例如「请关灯后从正面拍仪表，对准焦点」",
                    },
                },
                "required": ["reason", "suggestion"],
            },
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    """按工具名路由执行，返回 JSON 字符串（含中文 description）。任何异常都兜底为错误 JSON。"""
    args = args or {}
    try:
        if name == "search_manual":
            texts = rag.search(str(args.get("query", "")), top_k=3)
            return json.dumps({"description": "检索到的巡检规程条目", "items": texts},
                              ensure_ascii=False)
        if name == "get_device_profile":
            dev = store.get_device_profile(str(args.get("deviceId", ""))).model_dump()
            return json.dumps({"description": "设备档案/台账", "device": dev},
                              ensure_ascii=False)
        if name == "get_task":
            t = store.get_task(str(args.get("taskId", "")))
            return json.dumps({"description": "巡检任务信息",
                               "task": t.model_dump() if t else None},
                              ensure_ascii=False)
        if name == "list_devices":
            devs = [d.model_dump() for d in store.list_devices()]
            return json.dumps({"description": "设备清单", "count": len(devs),
                               "devices": devs[:20]}, ensure_ascii=False)
        if name == "get_config":
            cfg = {"confidenceThreshold": settings.CONFIDENCE_THRESHOLD,
                   "mock": settings.mock_mode, "llm": settings.has_llm,
                   "vision": settings.has_vision}
            return json.dumps({"description": "系统运行配置", "config": cfg},
                              ensure_ascii=False)
        if name == "similar_devices":
            dev_type = str(args.get("deviceType", ""))
            exclude = str(args.get("excludeDeviceId", ""))
            devs = [d for d in store.list_devices()
                    if dev_type in d.type and d.id != exclude]
            return json.dumps({"description": f"同类型({dev_type})其他设备",
                               "count": len(devs),
                               "devices": [d.model_dump() for d in devs[:10]]},
                              ensure_ascii=False)
        if name == "get_contacts":
            # 简化版：返回固定应急联系人（生产接用户表 + 部门表）
            device_id = str(args.get("deviceId", ""))
            area = str(args.get("area", ""))
            contacts = {
                "primary": {"name": "张工", "phone": "138****1234", "role": "区域巡检负责人"},
                "repair": {"name": "李师傅", "phone": "139****5678", "role": "维修班组"},
                "emergency": {"name": "值班电工", "phone": "137****9012", "role": "应急 7x24"},
                "context": f"设备{device_id} 区域{area}",
            }
            return json.dumps({"description": "应急联系人", "contacts": contacts},
                              ensure_ascii=False)
        if name == "ask_user_reshoot":
            reason = str(args.get("reason", "图像不可读"))
            suggestion = str(args.get("suggestion", "请重新拍摄"))
            msg = f"📸 需要重拍：{reason}\n💡 建议：{suggestion}\n请重新进入巡检页面上传一张更清晰的照片。"
            return json.dumps({"description": "请求巡检员重拍", "message": msg,
                               "type": "need_user_action", "action": "reshoot"},
                              ensure_ascii=False)
        return json.dumps({"description": f"未知工具 {name}", "error": "tool_not_found"},
                          ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        log.warning("工具 %s 执行失败: %s", name, e)
        return json.dumps({"description": f"工具 {name} 执行失败", "error": str(e)},
                          ensure_ascii=False)