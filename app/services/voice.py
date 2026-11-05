"""语音结构化抽取（主纲 §3.5.3）：口语 -> 槽位 + 阴性证据。

把巡检员口述的一句话解析成：
- slots.parts / phenomena / readings / sensory / actions
- negatives（阴性证据，如"没有异响"）—— 最值钱也最易漏
- readings[].approx = true（口述估算值不当真值，防误报）
"""
import logging

from app.config import settings
from app.services import llm

log = logging.getLogger("inspectagent.voice")

VOICE_SYSTEM = """你是配电房巡检语音解析助手。把巡检员口述的一段话解析成结构化槽位，只输出 JSON：
{
  "slots": {
    "parts": ["部位(如母线接头)"],
    "phenomena": ["标准现象词"],
    "readings": [{"item": "温度", "value": "78", "unit": "℃", "approx": true}],
    "sensory": ["触觉|嗅觉|听觉|视觉"],
    "actions": ["需停电复检等动作"]
  },
  "negatives": ["没有听到放电声等'没/无/未见'表述"],
  "severity": "轻微|明显|严重|未提及",
  "confidence": 0.8
}
规则：
1. 现象词只能用这些：发热/高温/异响/放电/异味/焦味/锈蚀/破损/松动/渗水/积水/积尘/指示灯异常/跳闸/漏液/鼓包
2. 口述的数值一律 approx=true（如"大概七八十度"），不得当真值
3. "没有/无/没听到/未见"类表述放进 negatives，别丢
4. 没提到的字段给空数组 []；severity 无法判断时填"未提及"
5. confidence 表示口述确定性：含糊/前后矛盾时给低值"""


def parse(voice_text: str) -> dict:
    """返回 VoiceOut 结构 dict。空文本/未配 Key 时返回确定性空结构。"""
    default = {
        "slots": {"parts": [], "phenomena": [], "readings": [],
                  "sensory": [], "actions": []},
        "negatives": [], "severity": "未提及", "confidence": 0.0,
    }
    text = (voice_text or "").strip()
    if not text:
        return default
    if settings.mock_mode:
        return default
    data = llm.chat_json(VOICE_SYSTEM, f"巡检员口述：{text}", default,
                         caller="voice")
    data.setdefault("slots", default["slots"])
    data.setdefault("negatives", [])
    data.setdefault("severity", "未提及")
    try:
        data["confidence"] = float(data.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        data["confidence"] = 0.0
    return data