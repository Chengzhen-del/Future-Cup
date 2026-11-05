"""视觉专岗 Agent —— 把视觉判读封装成可被状态机调用的专岗角色。

内部流程：先 assess_readable 判可读性 → 可读则调 read_meter / detect_defect /
check_environment 融合成 VisionOut 结构；不可读则返回 unreadable 结构的确定性降级结果。
每次 run 记录本次实际用到的视觉工具名到 self.last_tools。
mock / 无 key / 无图时返回 readable=False 的确定性空结构，绝不抛异常。
"""
from app.config import settings
from app.services import vision


class VisionAgent:
    def __init__(self):
        self.last_tools: list[str] = []

    def run(self, image_bytes: bytes, hint: str = "", device_type: str = "") -> dict:
        """返回 VisionOut 结构 dict。"""
        self.last_tools = []

        if not settings.has_vision or not image_bytes:
            self.last_tools.append("assess_readable")
            return self._unreadable("视觉模型不可用或无图像")

        if settings.VISION_MODE != "multi":
            self.last_tools.append("analyze")
            return vision.analyze_single(image_bytes, hint, device_type)

        self.last_tools.append("assess_readable")
        assess = vision.assess_readable(image_bytes)
        if not assess.get("readable"):
            return {
                "scene": assess.get("scene", ""),
                "readable": False,
                "indicators": [],
                "defects": [],
                "environment": dict(vision.DEFAULT_ENVIRONMENT),
                "unreadable": assess.get("unreadable") or ["整图（不可读）"],
                "riskHint": assess.get("riskHint", ""),
            }

        self.last_tools += ["read_meter", "detect_defect", "check_environment"]
        meters = vision.read_meter(image_bytes, hint, device_type)
        defects = vision.detect_defect(image_bytes, hint, device_type)
        env = vision.check_environment(image_bytes)
        return {
            "scene": assess.get("scene", ""),
            "readable": True,
            "indicators": meters.get("indicators", []),
            "defects": defects.get("defects", []),
            "environment": env.get("environment", dict(vision.DEFAULT_ENVIRONMENT)),
            "unreadable": assess.get("unreadable", []),
            "riskHint": assess.get("riskHint", ""),
        }

    @staticmethod
    def _unreadable(reason: str) -> dict:
        return {
            "scene": "",
            "readable": False,
            "indicators": [],
            "defects": [],
            "environment": dict(vision.DEFAULT_ENVIRONMENT),
            "unreadable": [reason],
            "riskHint": "",
        }