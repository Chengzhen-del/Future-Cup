"""巡检 Agent —— 手写 6 步状态机（不用 LangChain / LangGraph）。

六步：任务规划 → 语音解析 → 视觉判读 → 台账比对 → 手册检索 → 定级决策

设计要点：
- 每一步都是独立函数，单步失败不影响后续，只记 failed；每步有 15s 超时
- 每一步 yield 一个 step 事件，WebSocket 直接推给端侧渲染任务流卡片
- 语音槽位反向指导视觉"看哪里"；视觉/语音交叉验证，冲突则转人工
- 全程可离线：没有 Key 时走 mock，链路照样通
"""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import AsyncIterator

from app.config import settings
from app.schemas import (Finding, InspectReq, InspectResp, StepOut,
                         VisionOut, VoiceOut)
from app.agent.review_agent import ReviewAgent
from app.agent.vision_agent import VisionAgent
from app.services import llm, rag, store, voice

log = logging.getLogger("inspectagent.agent")

STEP_NAMES = ["任务规划", "语音解析", "视觉判读", "台账比对", "手册检索", "定级决策"]
STEP_TIMEOUT = 30.0        # 普通步骤（本地/轻量 LLM）
VISION_TIMEOUT = 60.0      # 视觉模型 + Base64 大图，冷启动常超 15s

LEVEL_MAP = {"正常": "正常", "关注": "关注", "异常": "异常", "紧急": "紧急",
             "normal": "正常", "warning": "关注", "abnormal": "异常", "critical": "紧急"}

PLAN_SYSTEM = """你是巡检任务规划助手。根据设备与现场描述，列出本轮要重点核对的检查项。
只输出 JSON：{"checklist":["检查项1","检查项2","检查项3"]}，不超过 5 项。"""

DECIDE_SYSTEM = """你是配电房巡检决策专家。依据给定的多模态观测事实（视觉判读 + 语音描述 + 台账 + 规范条款），输出定级结论。
只输出 JSON：{"level":"正常|关注|异常|紧急","confidence":0.0-1.0,"advice":"不超过50字的处置建议","reason":"一句话理由"}
定级标准：紧急=有放电/破损/焦糊味/异响等需立即停电；异常=超过规程限值或功能失效；
关注=偏离正常但不构成风险；正常=全部符合规程。
语音描述的估算值(approx)只能作参考，不能作为超标判定依据；视觉与语音冲突时以视觉为准。
confidence 低于 0.6 或存在冲突时如实给出低值。"""

REACT_SYSTEM = """你是智能巡检 Agent 的自主决策模块（ReAct 模式），负责判断当前证据是否足以定级。
- 若证据充分，直接用中文回答"证据充分"并简述理由，不要调用任何工具
- 若证据不足，调用一个最合适的工具补充（search_manual 查规范 / get_device_profile 查台账 / similar_devices 对比同类设备 / list_devices 看同配电房其他设备）
每轮最多调用一次工具，工具结果会返回给你，然后再次判断。"""


def _num(s) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", str(s or ""))
    return float(m.group()) if m else None


def _vision_findings(vdata: dict) -> list[Finding]:
    fs: list[Finding] = []
    for ind in vdata.get("indicators", []):
        fs.append(Finding(item=ind.get("name") or ind.get("kind", "仪表"),
                          value=ind.get("value", ""),
                          abnormal=bool(ind.get("abnormal", False)), basis="视觉判读"))
    for d in vdata.get("defects", []):
        fs.append(Finding(item=d.get("type", "外观缺陷"), value=d.get("detail", ""),
                          abnormal=bool(d.get("abnormal", True)), basis="视觉判读"))
    for k, v in (vdata.get("environment") or {}).items():
        fs.append(Finding(item=f"环境项·{k}", value="存在异常" if v else "正常",
                          abnormal=bool(v), basis="视觉判读"))
    return fs


def _voice_findings(vc: VoiceOut) -> list[Finding]:
    fs: list[Finding] = []
    for r in vc.slots.readings:
        fs.append(Finding(item=r.item or "口述读数", value=f"{r.value}{r.unit or ''}（估算）",
                          abnormal=False, basis="语音描述·未经视觉确认"))
    for p in vc.slots.phenomena:
        fs.append(Finding(item=p, value="口述存在", abnormal=True,
                          basis="语音描述·未经视觉确认"))
    for n in vc.negatives:
        fs.append(Finding(item=n, value="正常（阴性证据）", abnormal=False, basis="语音描述"))
    return fs


def _has_conflict(vdata: dict, vc: VoiceOut) -> bool:
    """同一检查项：视觉读数 vs 语音读数，差 >10 或 >15% 即判冲突（主纲 §3.5.4）。"""
    for ind in vdata.get("indicators", []):
        iv = _num(ind.get("value"))
        if iv is None:
            continue
        iname = ind.get("name", "")
        for r in vc.slots.readings:
            rv = _num(r.value)
            if rv is None:
                continue
            if r.item and iname and (r.item in iname or iname in r.item):
                diff = abs(iv - rv)
                base = max(abs(iv), abs(rv))
                if diff > 10 or (base and diff / base > 0.15):
                    return True
    return False


class InspectAgent:
    def __init__(self, req: InspectReq, image_bytes: bytes = b"",
                 request_id: str = ""):
        self.req = req
        self.image_bytes = image_bytes
        self.request_id = request_id
        self.session_id = uuid.uuid4().hex[:12]
        self.steps: list[StepOut] = []
        self.findings: list[Finding] = []
        self._ctx: dict = {}
        self._last_react_events: list[dict] = []  # P2 ReAct Loop 事件
        self._llm_fail_count: int = 0  # 🔒 P2-1: LLM 熔断计数器

    async def _run_step(self, name: str, fn) -> tuple:
        """在独立线程执行单步（含超时兜底 + LLM 熔断追踪）。"""
        t0 = time.time()
        timeout = VISION_TIMEOUT if name == "视觉判读" else STEP_TIMEOUT
        subs: list[dict] = []
        try:
            raw = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
            status = "done"
            if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], list):
                detail, subs = raw
            else:
                detail = raw
        except asyncio.TimeoutError:
            detail, status = "失败：单步超时", "failed"
            self._llm_fail_count += 1
        except Exception as e:  # noqa: BLE001
            # 🔒 P2-1: LLMError 计入熔断
            if "LLMError" in type(e).__name__ or "LLM 熔断" in str(e):
                self._llm_fail_count += 1
            detail, status = f"失败：{e}", "failed"
        return str(detail)[:200], subs, status, int((time.time() - t0) * 1000)

    # ---------- 单步实现（返回 (detail, subSteps) 元组） ----------
    def _plan(self) -> tuple[str, list]:
        subs = [{"text": f"设备类型：{self.req.deviceType}", "level": 2, "status": "info"}]
        if self.req.voiceText:
            subs.append({"text": f"语音摘要：{self.req.voiceText[:40]}", "level": 2, "status": "info"})
        if settings.mock_mode:
            checklist = ["母线接头温度", "柜体外观与放电痕迹", "仪表与指示灯", "环境温湿度"]
            subs.append({"text": f"Mock 模式，直接用默认清单", "level": 2, "status": "info"})
        else:
            subs.append({"text": f"调用 DeepSeek 生成 checklist…", "level": 2, "status": "info"})
            system = PLAN_SYSTEM[:60] + "…"
            subs.append({"text": f"System prompt: {system}", "level": 3, "status": "info"})
            data = llm.chat_json(PLAN_SYSTEM,
                                 f"设备：{self.req.deviceName or self.req.deviceId}（{self.req.deviceType}）\n"
                                 f"位置：{self.req.location}\n语音描述：{self.req.voiceText}",
                                 {"checklist": ["接头温度", "外观", "指示灯", "环境"]},
                                 schema={"required": ["checklist"]},
                                 caller="plan", session_id=self.session_id)
            checklist = data.get("checklist", [])[:5]
            subs.append({"text": f"LLM 返回 {len(checklist)} 项重点核对", "level": 2, "status": "ok"})
        self._ctx["checklist"] = checklist
        for i, c in enumerate(checklist):
            subs.append({"text": f"  [{i+1}] {c}", "level": 3, "status": "ok"})
        return "、".join(checklist), subs

    def _voice_parse(self) -> tuple[str, list]:
        subs = [{"text": f"原始语音文本：{self.req.voiceText[:50] or '（空）'}", "level": 2, "status": "info"}]
        vc = VoiceOut(**voice.parse(self.req.voiceText))
        self._ctx["voiceSlots"] = vc
        self.findings.extend(_voice_findings(vc))
        subs.append({"text": f"解析结果：部位 {len(vc.slots.parts)} 项, 现象 {len(vc.slots.phenomena)} 项", "level": 2, "status": "ok"})
        if vc.slots.parts:
            subs.append({"text": f"  部位槽位：{vc.slots.parts}", "level": 3, "status": "ok"})
        if vc.slots.phenomena:
            subs.append({"text": f"  现象槽位：{vc.slots.phenomena}", "level": 3, "status": "ok"})
        if vc.negatives:
            subs.append({"text": f"  阴性证据：{vc.negatives}", "level": 3, "status": "info"})
        subs.append({"text": f"严重度评估：{vc.severity}", "level": 2, "status": "info"})
        return (f"部位 {len(vc.slots.parts)} 项，现象 {len(vc.slots.phenomena)} 项，"
                f"阴性证据 {len(vc.negatives)} 项，严重度 {vc.severity}"), subs

    def _vision(self) -> tuple[str, list]:
        subs = [{"text": f"VISION_MODE = {settings.VISION_MODE}（{'单次综合判读' if settings.VISION_MODE == 'single' else '四工具聚焦判读'}）", "level": 2, "status": "info"}]
        if not self.image_bytes:
            subs.append({"text": "未上传现场图片，视觉模块返回空", "level": 2, "status": "warn"})
            subs.append({"text": "后续决策将降低置信度并标记 needHuman", "level": 3, "status": "warn"})
        voice_hint = self.req.voiceText
        va = VisionAgent()
        subs.append({"text": f"调用 VisionAgent.run()…", "level": 2, "status": "info"})
        vdata = va.run(self.image_bytes, voice_hint, self.req.deviceType)
        self._ctx["visionOut"] = vdata
        self._ctx["visionTools"] = va.last_tools
        tools = va.last_tools or []
        if tools:
            for t in tools:
                subs.append({"text": f"  → 执行工具: {t}", "level": 3, "status": "info"})
        else:
            subs.append({"text": "  → 无工具调用（单模式一次综合）", "level": 3, "status": "info"})

        if vdata.get("readable") is False:
            hint = vdata.get("riskHint") or "图像不可读"
            subs.append({"text": f"⚠ 图像不可读：{hint}", "level": 2, "status": "warn"})
            return f"视觉工具: {','.join(tools) if tools else '无'}；{hint}", subs

        indicators = vdata.get("indicators", [])
        defects = vdata.get("defects", [])
        subs.append({"text": f"✅ 视觉可读，检测到 {len(indicators)} 个仪表 / {len(defects)} 个缺陷", "level": 2, "status": "ok"})
        for ind in indicators:
            flag = "⚠" if ind.get("abnormal") else "✓"
            subs.append({"text": f"  {flag} {ind.get('name','')} = {ind.get('value','')}（{ind.get('basis','')}）",
                        "level": 3, "status": "warn" if ind.get("abnormal") else "ok"})
        for d in defects:
            subs.append({"text": f"  ⚠ 缺陷: {d.get('type','')} - {d.get('detail','')}", "level": 3, "status": "warn"})
        env = vdata.get("environment", {})
        if env:
            env_parts = [f"{k}={v}" for k, v in env.items()]
            subs.append({"text": f"环境评估：{' / '.join(env_parts)}", "level": 3, "status": "info"})

        self.findings.extend(_vision_findings(vdata))
        base = vdata.get("scene") or vdata.get("riskHint") or "判读完成"
        return f"视觉工具: {','.join(tools) if tools else '无'}；{base}", subs

    def _ledger(self) -> tuple[str, list]:
        subs = [{"text": f"查询设备档案 id={self.req.deviceId or 'D-3001'}", "level": 2, "status": "info"}]
        dev = store.get_device_profile(self.req.deviceId or "D-3001").model_dump()
        subs.append({"text": f"设备档案：{dev.get('name', '')} 额定温度 {dev.get('ratedTemp')}℃ / 湿度 {dev.get('ratedHumidity')}%RH", "level": 2, "status": "ok"})
        s = self.req.sensor
        if s and s.temperature is not None:
            limit = dev.get("ratedTemp")
            if limit is not None:
                abnormal = s.temperature > limit
                self.findings.append(Finding(
                    item="实测温度", value=f"{s.temperature}℃（限值 {limit}℃）",
                    abnormal=abnormal, basis="传感器" + ("·模拟值" if s.simulated else "")))
                status = "warn" if abnormal else "ok"
                subs.append({"text": f"  {'⚠' if abnormal else '✓'} 实测 {s.temperature}℃ vs 限值 {limit}℃ {'超限!' if abnormal else '正常'}",
                            "level": 3, "status": status})
        if s and s.humidity is not None and s.humidity > 80:
            self.findings.append(Finding(item="环境湿度", value=f"{s.humidity}%RH",
                                         abnormal=True, basis="传感器"))
            subs.append({"text": f"  ⚠ 湿度 {s.humidity}%RH 超限", "level": 3, "status": "warn"})
        self._ctx["device"] = dev
        history = dev.get("history", "无历史台账")[:80]
        subs.append({"text": f"历史台账：{history}", "level": 3, "status": "info"})
        return history, subs

    def _manual(self) -> tuple[str, list]:
        query = " ".join([self.req.deviceName or "", self.req.voiceText]
                         + [f.item for f in self.findings])[:200]
        subs = [{"text": f"检索 query: {query[:60]}", "level": 2, "status": "info"}]
        rules = rag.search(query or "配电柜巡检规范", top_k=3)
        self._ctx["rules"] = rules
        subs.append({"text": f"RAG 命中 {len(rules)} 条规范", "level": 2, "status": "ok"})
        for i, r in enumerate(rules[:3]):
            subs.append({"text": f"  [{i+1}] {r[:80]}…", "level": 3, "status": "ok"})
        return (rules[0][:60] + "…" if rules else "未命中规范条目"), subs

    def _decide(self) -> tuple[str, list]:
        """第二轮：单次 LLM 定级 + 独立复核 真并行。"""
        subs = [{"text": f"待决策 findings 共 {len(self.findings)} 条", "level": 2, "status": "info"}]
        facts_lines = []
        for f in self.findings:
            flag = "⚠" if f.abnormal else "✓"
            line = f"{flag} {f.item}: {f.value}（{'异常' if f.abnormal else '正常'}）"
            facts_lines.append(line)
            subs.append({"text": f"  {line}", "level": 3, "status": "warn" if f.abnormal else "ok"})

        facts = "\n".join(f"- {f.item}: {f.value}（{'异常' if f.abnormal else '正常'}，依据：{f.basis}）"
                          for f in self.findings) or "- 无有效观测"
        rules = "\n".join(self._ctx.get("rules", []))
        if settings.mock_mode:
            subs.append({"text": "Mock 模式，跳过 LLM + ReviewAgent", "level": 2, "status": "info"})
            subs.append({"text": "  → 主决策返回: 异常 / 0.82", "level": 3, "status": "info"})
            return "异常", (0.82, "3号配电柜接头温度 78℃（限值 70℃），建议 24 小时内停电复检并紧固接头。"), subs

        vc: VoiceOut = self._ctx.get("voiceSlots")
        voice_line = (f"语音槽位：部位{vc.slots.parts} 现象{vc.slots.phenomena} "
                      f"阴性{vc.negatives} 严重度{vc.severity}") if vc else "无语音"
        user_msg = (f"设备：{self.req.deviceName or self.req.deviceId}（{self.req.deviceType}）\n"
                    f"观测事实：\n{facts}\n相关规范：\n{rules}\n{voice_line}")

        subs.append({"text": "主决策：调用 DeepSeek chat_json(DECIDE_SYSTEM, facts, rules, voiceSlots)…", "level": 2, "status": "info"})
        default = {"level": "关注", "confidence": 0.5,
                   "advice": "建议人工复核", "reason": "模型未返回结果"}
        data = llm.chat_json(DECIDE_SYSTEM, user_msg, default,
                             schema={"required": ["level", "confidence", "advice"],
                                     "types": {"confidence": (int, float)}},
                             caller="decide", session_id=self.session_id)
        level = LEVEL_MAP.get(str(data.get("level", "关注")).strip(), "关注")
        try:
            conf = float(data.get("confidence", 0.5) or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        advice = str(data.get("advice", "建议人工复核"))
        subs.append({"text": f"  → 主决策返回: {level} / 置信度 {conf}", "level": 3, "status": "info"})

        subs.append({"text": "独立复核：ReviewAgent 并行运行（只看证据，不看决策）…", "level": 2, "status": "info"})
        subs.append({"text": "  → ReviewAgent verdict: 同意/存疑/驳回，suggestLevel", "level": 3, "status": "info"})

        subs.append({"text": "本地融合：取更严重定级 / 均值置信度 / 转人工阈值 0.60", "level": 2, "status": "info"})
        return level, (conf, advice), subs

    def _review_evidence(self) -> dict:
        """复核证据：仅多模态事实，不含主决策输出（决策/复核真并行）。"""
        vdata = self._ctx.get("visionOut", {}) or {}
        vc = self._ctx.get("voiceSlots")
        dev = self._ctx.get("device", {}) or {}
        rules = self._ctx.get("rules", []) or []

        if isinstance(vc, VoiceOut):
            voice_s = (f"部位{vc.slots.parts} 现象{vc.slots.phenomena} "
                       f"阴性{vc.negatives} 严重度{vc.severity}")
        else:
            voice_s = ""
        vis_parts = []
        for ind in vdata.get("indicators", []):
            vis_parts.append(f"{ind.get('name', '')}{ind.get('value', '')}"
                             f"({'异常' if ind.get('abnormal') else '正常'})")
        for d in vdata.get("defects", []):
            vis_parts.append(f"缺陷:{d.get('type', '')} {d.get('detail', '')}")
        if vdata.get("readable") is False:
            vis_parts.append(f"图像不可读:{vdata.get('riskHint', '')}")

    # ============= P2: ReAct Loop 辅助方法 =============
    def _build_react_evidence(self, prev_observations: list[str]) -> str:
        """把前五步已收集的 evidence 拼成 ReAct prompt。"""
        lines = []
        for f in self.findings:
            flag = "⚠" if f.abnormal else "✓"
            lines.append(f"  {flag} {f.item}: {f.value}（依据：{f.basis}）")
        if not lines:
            lines.append("  （无有效观测）")
        if prev_observations:
            lines.append("\n已通过工具补充：")
            for obs in prev_observations:
                lines.append(f"  📚 {obs[:120]}")
        return "\n".join(lines)

    def _run_react_loop(self, prompt: str, prev_obs: list[str], max_rounds: int = 3) -> list[str]:
        """🟢 原生 Function Calling ReAct 循环（llm.tool_loop 封装 tools= 参数）。
        模型自主判断是否调工具；返回补充的 observations 列表。"""
        from app.agent import tools as agent_tools
        final_text, events = llm.tool_loop(
            REACT_SYSTEM, prompt, agent_tools.TOOLS,
            max_rounds=max_rounds, caller="react", session_id=self.session_id)

        observations = list(prev_obs)
        for ev in events:
            if ev.get("type") == "tool":
                args_s = json.dumps(ev.get("args", {}), ensure_ascii=False)
                observations.append(f"{ev['name']}({args_s}): {ev.get('observation', '')[:200]}")
                self._last_react_events.append({
                    "round": ev["round"], "action": ev["name"],
                    "args": ev.get("args", {}),
                    "observation": ev.get("observation", "")[:200]})
            else:
                self._last_react_events.append({
                    "round": ev["round"], "thought": ev.get("text", "")})
        if final_text:
            self._ctx["reactConclusion"] = final_text
        return observations

    def _review_evidence(self) -> dict:
        """复核证据：仅多模态事实，不含主决策输出（决策/复核真并行）。"""
        vdata = self._ctx.get("visionOut", {}) or {}
        vc = self._ctx.get("voiceSlots")
        dev = self._ctx.get("device", {}) or {}
        rules = self._ctx.get("rules", []) or []

        if isinstance(vc, VoiceOut):
            voice_s = (f"部位{vc.slots.parts} 现象{vc.slots.phenomena} "
                       f"阴性{vc.negatives} 严重度{vc.severity}")
        else:
            voice_s = ""
        vis_parts = []
        for ind in vdata.get("indicators", []):
            vis_parts.append(f"{ind.get('name', '')}{ind.get('value', '')}"
                             f"({'异常' if ind.get('abnormal') else '正常'})")
        for d in vdata.get("defects", []):
            vis_parts.append(f"缺陷:{d.get('type', '')} {d.get('detail', '')}")
        if vdata.get("readable") is False:
            vis_parts.append(f"图像不可读:{vdata.get('riskHint', '')}")
        vision_s = "；".join(vis_parts)

        ledger_s = ""
        if dev:
            ledger_s = (f"{dev.get('name', '')} 额定温度{dev.get('ratedTemp')}℃ "
                        f"额定湿度{dev.get('ratedHumidity')}%RH；历史:{str(dev.get('history', ''))[:80]}")
        manual_s = "；".join(rules[:2])
        return {"voice": voice_s, "vision": vision_s, "ledger": ledger_s, "manual": manual_s}

    def _merge_decision(self, level: str, conf: float, advice: str,
                        review: dict) -> tuple[str, float, str, bool]:
        """本地融合决策与独立复核（零 LLM）：取更严重定级、均值置信度、转人工标记。"""
        rank = {"正常": 0, "关注": 1, "异常": 2, "紧急": 3}
        level = LEVEL_MAP.get(str(level).strip(), "关注")
        verdict = str(review.get("verdict") or "同意")
        suggest = LEVEL_MAP.get(str(review.get("suggestLevel") or level).strip(), "关注")

        suggest_heavier = rank.get(suggest, 0) > rank.get(level, 0)
        new_level = suggest if suggest_heavier else level

        rval = review.get("confidence")
        rconf = float(rval) if isinstance(rval, (int, float)) and not isinstance(rval, bool) else conf
        new_conf = (conf + rconf) / 2.0

        need_human = False
        if verdict == "驳回" or suggest_heavier:
            new_conf *= 0.85
            need_human = True
        if verdict == "存疑":
            new_conf *= 0.90
        new_conf = min(max(new_conf, 0.0), 1.0)

        reason = str(review.get("reason", "") or "").strip()
        if reason and verdict in ("存疑", "驳回"):
            advice = f"{advice}；复核：{reason}" if advice else f"复核：{reason}"
        return new_level, new_conf, advice, need_human

    # ---------- 编排 ----------
    def _collect_incomplete_fields(self) -> list[str]:
        """扫一遍多模态证据，列出档案里不完整的字段。"""
        missing: list[str] = []
        vdata = self._ctx.get("visionOut", {}) or {}
        vc = self._ctx.get("voiceSlots")
        if vdata.get("readable") is False:
            missing.append("visual_unreadable")
        if not vdata.get("indicators") and not vdata.get("defects"):
            missing.append("visual_empty")
        if not self.req.voiceText or (isinstance(vc, VoiceOut) and not vc.slots.parts and not vc.slots.phenomena):
            missing.append("voice_missing")
        if not self.req.sensor:
            missing.append("sensor_missing")
        elif self.req.sensor.simulated:
            missing.append("sensor_simulated")
        if not self.image_bytes:
            missing.append("image_missing")
        return missing

    def _generate_follow_up(self, incomplete: list[str]) -> list[str]:
        """根据缺失字段，生成 2-3 个反问。"""
        if not settings.has_llm or settings.mock_mode:
            # mock / 无 key 时给固定反问，保证端侧有东西显示
            fixed: list[str] = []
            if "visual_unreadable" in incomplete or "visual_empty" in incomplete:
                fixed.append("图片看得不太清楚，能否换个角度再拍一张？")
            if "voice_missing" in incomplete:
                fixed.append("没收到语音描述，请口述一下现场观察到的情况（如有无异味、异响、温度感受等）。")
            if "sensor_missing" in incomplete:
                fixed.append("没有传感器数据，能目测一下仪表读数吗？")
            if "image_missing" in incomplete:
                fixed.append("没有现场照片，请补拍一张设备全景和一张关键部位特写。")
            return fixed[:3]

        missing_desc = "、".join(incomplete)
        # 决策置信度低也触发反问
        level = (self._ctx.get("decision") or {}).get("level", "")
        conf = (self._ctx.get("decision") or {}).get("confidence", 0)
        extra = ""
        if conf < 0.7:
            extra = f"，且当前决策置信度仅 {conf:.2f}，信息不足"
        system = ("你是巡检现场的智能助手。根据下述档案缺失情况，向巡检员提出最多 3 个简洁、可操作的补充问题。"
                  "问题要口语化、不超过 20 字。只输出 JSON 数组。")
        user = f"缺失字段：{missing_desc}{extra}\n设备：{self.req.deviceName}（{self.req.deviceType}）"
        default = {"questions": []}
        data = llm.chat_json(system, user, default,
                             schema={"required": ["questions"]},
                             caller="followup", session_id=self.session_id)
        qs = data.get("questions", [])
        return [str(q) for q in qs if q][:3]

    def _apply_clarifications(self) -> str:
        """把端侧补答追加进 voiceText，作为第二轮增强。"""
        clar = self.req.clarifications or {}
        if not clar:
            return ""
        answers = clar.get("answers", [])
        qa_text = ""
        if isinstance(answers, list):
            qa_text = " ".join(str(a) for a in answers if a)
        elif isinstance(clar, dict):
            qa_text = " ".join(str(v) for v in clar.values() if v)
        if qa_text:
            self.req.voiceText = (self.req.voiceText + " [补答] " + qa_text).strip()
        return qa_text

    async def run(self) -> AsyncIterator[dict]:
        """产出事件流：step / sub_step / token / final / memory_hit。"""
        t_start = time.time()
        # mode → VISION_MODE 映射
        import os as _os
        _os.environ["VISION_MODE"] = "multi" if self.req.mode == "detailed" else "single"
        settings.VISION_MODE = _os.environ["VISION_MODE"]

        if settings.mock_mode:
            yield {"type": "step", "step": StepOut(name="环境自检", status="done",
                                                   detail="未配置大模型 Key，启用 mock 模式").model_dump()}

        # ========== P0 记忆加载 ==========
        memories = store.load_recent_memories(self.req.deviceId or None, limit=5)
        self._ctx["historyMemories"] = memories
        if memories:
            # 把历史记忆塞进 prompt 上下文，让 LLM 能引用
            hist_lines = []
            for m in memories:
                hist_lines.append(
                    f"- 时间 {m['capturedAt'] or m['createdAt']}  结果 {m['level']}  摘要：{m['summary'][:100]}")
            hist_prompt = "历史巡检记忆：\n" + "\n".join(hist_lines)
            # 🔒 P1-1 Token budget 截断：超 500 字自动裁掉最老的
            if len(hist_prompt) > 500:
                hist_prompt = "历史巡检记忆（已截断）：\n" + "\n".join(hist_lines[:3])
            self._ctx["historyPrompt"] = hist_prompt
            yield {"type": "sub_step", "stepName": "任务规划",
                   "subStep": {"text": f"🔍 命中 {len(memories)} 条历史巡检记忆", "level": 2, "status": "info"}}
            for m in memories[:3]:
                yield {"type": "sub_step", "stepName": "任务规划",
                       "subStep": {"text": f"  → {m['capturedAt'] or '未知时间'} {m['level']}: {m['summary'][:60]}",
                                   "level": 3, "status": "info"}}
            # 推 memory_hit 事件让前端也展示
            yield {"type": "memory_hit", "memories": memories}

        # 如果有 clarifications（第二轮），先合并补答
        if self.req.clarifications:
            yield {"type": "step", "step": StepOut(name="档案补全", status="running",
                                                   detail="正在整合用户补答…").model_dump()}
            merged = self._apply_clarifications()
            yield {"type": "step", "step": StepOut(name="档案补全", status="done",
                                                   detail=f"补答：{merged[:40] or '无'}").model_dump()}

        # 第一轮：5 个感知/检索动作真并行（LLM 为同步 SDK，to_thread 卸载避免阻塞事件循环）
        handlers = [self._plan, self._voice_parse, self._vision, self._ledger, self._manual]
        for name in STEP_NAMES[:5]:
            yield {"type": "step", "step": StepOut(name=name, status="running").model_dump()}
        results = await asyncio.gather(
            *(self._run_step(n, f) for n, f in zip(STEP_NAMES[:5], handlers)))
        for name, (detail, subs, status, ms) in zip(STEP_NAMES[:5], results):
            so = StepOut(name=name, status=status, detail=detail, durationMs=ms, subSteps=subs)
            self.steps.append(so)
            yield {"type": "step", "step": so.model_dump()}

        # 🔒 P2-1: LLM 熔断 - 3 次 LLMError → 自动切 mock 降级（不影响服务整体）
        if self._llm_fail_count >= 3:
            log.warning("LLM 连续 %s 次失败，本轮自动降级 mock 模式", self._llm_fail_count)
            yield {"type": "sub_step", "stepName": "环境自检",
                   "subStep": {"text": f"⚠️ LLM 连续 {self._llm_fail_count} 次失败，本轮自动降级为 mock 结果",
                               "level": 2, "status": "warn"}}
            settings.mock_mode = True

        # ========== P2: ReAct Loop（自主工具调用，最多 3 轮） ==========
        react_observations: list[str] = []
        yield {"type": "sub_step", "stepName": "定级决策",
               "subStep": {"text": "🧠 Agent 自主决策环：检查证据是否充分，不足则自动调工具补证据",
                           "level": 2, "status": "info"}}

        if not settings.mock_mode:
            react_evidence = self._build_react_evidence(react_observations)
            react_prompt = (
                f"设备：{self.req.deviceName or self.req.deviceId}（{self.req.deviceType}）\n"
                f"已收集证据：\n{react_evidence}\n"
                f"历史背景：\n{self._ctx.get('historyPrompt', '（无历史记忆）')}\n\n"
                f"请判断证据是否足以定级；不足则调用工具补充，充分则直接回答'证据充分'。"
            )
            react_observations = self._run_react_loop(react_prompt, react_observations, max_rounds=3)

        # 把 ReAct 补充的 observations 塞进 _ctx，让 _decide 也能引用
        if react_observations:
            self._ctx["reactObservations"] = react_observations

        # 把 ReAct 过程推给前端（sub_step 形式，在定级决策下嵌套）
        for ev in self._last_react_events:
            if ev.get("action"):
                text = f"🔧 Round {ev['round']}: 调 {ev['action']}({json.dumps(ev['args'], ensure_ascii=False)})"
                yield {"type": "sub_step", "stepName": "定级决策",
                       "subStep": {"text": text, "level": 3, "status": "info"}}
            else:
                text = f"🧠 Round {ev['round']}: {ev.get('thought', '')}"
                yield {"type": "sub_step", "stepName": "定级决策",
                       "subStep": {"text": text, "level": 3, "status": "info"}}

        # 第二轮：决策 + 独立复核 真并行（复核只看证据，不看决策）
        t0 = time.time()
        yield {"type": "step", "step": StepOut(name=STEP_NAMES[5], status="running").model_dump()}
        try:
            decide_raw, review = await asyncio.gather(
                asyncio.to_thread(self._decide),
                asyncio.to_thread(lambda: ReviewAgent().review(self._review_evidence())),
            )
            # decide_raw: (level, (conf, advice), subs)  or mock: ("异常", (0.82, advice_str), subs)
            level, conf_tuple, decide_subs = decide_raw
            conf, advice = conf_tuple
            # 把 ReAct 事件也合并进定级决策的 subSteps（HTTP 模式也能展示）
            all_subs = list(decide_subs)
            all_subs.insert(0, {"text": "🧠 Agent 自主决策环：检查证据是否充分，不足则自动调工具补证据",
                                "level": 2, "status": "info"})
            for ev in self._last_react_events:
                if ev.get("action"):
                    all_subs.append({"text": f"🔧 Round {ev['round']}: 调 {ev['action']}({json.dumps(ev['args'], ensure_ascii=False)})",
                                     "level": 3, "status": "info"})
                else:
                    all_subs.append({"text": f"🧠 Round {ev['round']}: {ev.get('thought', '')}",
                                     "level": 3, "status": "info"})
            so_decide = StepOut(name=STEP_NAMES[5], status="running",
                                detail=f"主决策 {level} / 置信度 {conf:.2f}",
                                subSteps=all_subs)
            yield {"type": "step", "step": so_decide.model_dump()}
            yield {"type": "sub_step", "stepName": STEP_NAMES[5],
                   "subStep": {"text": f"ReviewAgent verdict: {review}", "level": 2, "status": "info"}}
            level, conf, advice, merge_need = self._merge_decision(level, conf, advice, review)
            status = "done"
        except Exception as e:  # noqa: BLE001
            level, conf, advice, merge_need, status = ("关注", 0.40,
                f"定级失败，已转人工复核：{e}", True, "failed")

        # 归一化 + 封顶 + 转人工
        level = LEVEL_MAP.get(str(level).strip(), "关注")
        conf = min(max(conf, 0.0), 1.0)
        advice = str(advice)[:120]
        vdata = self._ctx.get("visionOut", {})
        vc = self._ctx.get("voiceSlots")
        conflict = bool(vc and _has_conflict(vdata, vc))
        self._ctx["conflict"] = conflict
        self._ctx["decision"] = {"level": level, "confidence": conf}
        if conflict or vdata.get("readable") is False:
            conf = min(conf, 0.60)
        need_human = merge_need or conf < settings.CONFIDENCE_THRESHOLD

        ms = int((time.time() - t0) * 1000)
        so_final = StepOut(name=STEP_NAMES[5], status=status,
                           detail=f"{level}（置信度 {conf:.2f}）",
                           durationMs=ms, subSteps=decide_subs)
        self.steps.append(so_final)
        yield {"type": "step", "step": so_final.model_dump()}

        # 第三轮：反问生成（只在第一轮且有缺失时触发；第二轮 clarifications 存在则跳过）
        follow_ups: list[str] = []
        incomplete = self._collect_incomplete_fields()
        if incomplete and not self.req.clarifications and conf < 0.85:
            yield {"type": "step", "step": StepOut(name="档案完善", status="running",
                                                   detail=f"检测到缺失：{'、'.join(incomplete[:3])}").model_dump()}
            follow_ups = self._generate_follow_up(incomplete)
            yield {"type": "step", "step": StepOut(name="档案完善", status="done",
                                                   detail=f"生成 {len(follow_ups)} 个补充问题").model_dump()}

        for ch in advice:
            yield {"type": "token", "text": ch}
        wo = None
        if level in ("异常", "紧急"):
            wo = store.create_workorder(self.req.taskId, self.req.deviceId,
                                        self.req.deviceName, level, advice)

        voice_out = vc if isinstance(vc, VoiceOut) else VoiceOut()
        vision_out = VisionOut(**{k: v for k, v in vdata.items()
                                  if k in VisionOut.model_fields}) if vdata else VisionOut()
        duration_ms = int((time.time() - t_start) * 1000)
        resp = InspectResp(sessionId=self.session_id, level=level,
                           confidence=round(conf, 2), advice=advice,
                           findings=self.findings, voiceSlots=voice_out,
                           vision=vision_out, steps=self.steps,
                           workOrderId=wo.id if wo else None,
                           needHuman=need_human, mock=settings.mock_mode,
                           durationMs=duration_ms,
                           followUpQuestions=follow_ups,
                           incompleteFields=incomplete,
                           memories=self._ctx.get("historyMemories", []))

        if not settings.mock_mode:
            resp = store.finalize_inspection(self.req, resp, self.image_bytes,
                                             self.request_id)
            # ========== P0 记忆落库 ==========
            try:
                store.upsert_session(self.session_id, self.req)
                store.save_inspection_memory(self.session_id, self.req, resp)
                # P1: 异步入 RAG 索引（后台，不阻塞主流程）
                try:
                    asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: rag.add_memory_to_index(
                            mem_id="mem-" + str(resp.inspectionId or uuid.uuid4().hex),
                            summary=resp.advice[:120],
                            device_id=self.req.deviceId or "",
                            device_type=self.req.deviceType or "",
                            level=resp.level,
                            keywords=" | ".join([f.item for f in resp.findings]),
                        ))
                except Exception:
                    pass  # RAG 挂了不影响主流程
                yield {"type": "sub_step", "stepName": "档案完善",
                       "subStep": {"text": f"✅ 巡检记忆已入库（inspectionId={resp.inspectionId}）",
                                   "level": 2, "status": "ok"}}
            except Exception as e:
                log.warning("记忆落库失败（不影响主流程）：%s", e)
        yield {"type": "final", "data": resp.model_dump()}


async def run_once(req: InspectReq, image_bytes: bytes = b"",
                   request_id: str = "") -> InspectResp:
    """HTTP 一次性调用（不走 WS）。"""
    agent = InspectAgent(req, image_bytes, request_id)
    final: dict = {}
    # 🟢 P3-1: Trace buffer - async for 消费时同时收集
    trace_events: list[dict] = []
    async for ev in agent.run():
        trace_events.append(ev)
        if ev["type"] == "final":
            final = ev["data"]
    # 🟢 P3-1: Trace 持久化（事件已全部收集）
    if trace_events and final:
        try:
            resp_obj = InspectResp(**final)
            total_ms = resp_obj.durationMs or 0
            import asyncio as _asyncio
            _asyncio.get_running_loop().run_in_executor(
                None, lambda: store.save_trace(
                    agent.session_id, trace_events, resp_obj, req, total_ms))
        except Exception as e:
            log.warning("Trace 落库失败（不影响主流程）：%s", e)
    if not final:
        return InspectResp(sessionId="mock-" + uuid.uuid4().hex[:8], level="异常",
                           confidence=0.82, advice="链路异常，已给出兜底结论",
                           findings=[], steps=[], needHuman=True, mock=True)
    return InspectResp(**final)