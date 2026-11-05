"""复核 Agent —— 独立复核员：只看多模态证据、不看主决策输出，防误报/漏报。

输入 evidence（voice / vision / ledger / manual 摘要，不含主决策），
用文本大模型扮演独立复核员，输出 {"verdict", "reason", "confidence", "suggestLevel"}。
失败 / mock / 无 key 时返回保守默认结果，绝不抛异常。
"""
import logging

from app.config import settings
from app.services import llm

log = logging.getLogger("inspectagent.review_agent")

REVIEW_SYSTEM = """你是配电房巡检的独立复核员。你的职责是依据下述多模态证据，独立给出复核定级，
重点防止误报（把正常当成异常）和漏报（把异常当成正常）。只输出 JSON，不要任何多余文字：
{
  "verdict": "同意|存疑|驳回",
  "reason": "一句话复核理由",
  "confidence": 0.0-1.0,
  "suggestLevel": "正常|关注|异常|紧急"
}
规则：
1. 证据充分、结论明确 → verdict「同意」；证据不足或相互冲突 → verdict「存疑」；证据明显指向更高风险却被识别为低风险 → verdict「驳回」。
2. confidence 给出你复核后认为的合理值（0~1）。
3. suggestLevel 给出你认为最稳妥的定级：正常|关注|异常|紧急。
4. 语音描述只是估算参考，视觉/台账证据权重更高；宁可信其有（防漏报）但不能臆造（防误报）。"""

_LEVELS = ("正常", "关注", "异常", "紧急")
_VERDICTS = ("同意", "存疑", "驳回")


def _clamp_conf(v) -> float:
    try:
        f = float(v)
        return min(max(f, 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.5


class ReviewAgent:
    def review(self, evidence: dict) -> dict:
        evidence = evidence or {}

        fallback = {"verdict": "同意", "reason": "", "confidence": 0.5, "suggestLevel": "关注"}
        if settings.mock_mode or not settings.has_llm:
            return fallback

        voice_s = str(evidence.get("voice", ""))
        vision_s = str(evidence.get("vision", ""))
        ledger_s = str(evidence.get("ledger", ""))
        manual_s = str(evidence.get("manual", ""))
        user_msg = (
            f"语音摘要：{voice_s or '无'}\n"
            f"视觉摘要：{vision_s or '无'}\n"
            f"台账摘要：{ledger_s or '无'}\n"
            f"命中规范：{manual_s or '无'}"
        )
        try:
            data = llm.chat_json(REVIEW_SYSTEM, user_msg, fallback,
                                 caller="review")
            verdict = str(data.get("verdict", "同意"))
            if verdict not in _VERDICTS:
                verdict = "同意"
            suggest = str(data.get("suggestLevel", "关注"))
            if suggest not in _LEVELS:
                suggest = "关注"
            return {
                "verdict": verdict,
                "reason": str(data.get("reason", "")),
                "confidence": _clamp_conf(data.get("confidence", 0.5)),
                "suggestLevel": suggest,
            }
        except Exception as e:  # noqa: BLE001
            log.warning("复核模型调用失败，采用保守默认: %s", e)
            return fallback