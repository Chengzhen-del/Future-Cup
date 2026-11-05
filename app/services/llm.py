"""文本大模型（DeepSeek，OpenAI 协议）。

原则：
1. 只在这里出现 openai 客户端，别的文件不许直接 new client
2. 没 Key / 调用失败 -> 抛 LLMError，由上层降级，绝不把异常甩给端侧
"""
import json
import logging
import threading
import time
from typing import Any

from app.config import settings

log = logging.getLogger("inspectagent.llm")

_client = None

# 🔒 P0-1: 并发信号量 - 最多同时 3 个 LLM 调用，避免打爆配额
_llm_semaphore = threading.Semaphore(3)

# 🔒 P2-1: 熔断计数器 - 模型连续失败累计，超过阈值自动降级
_circuit_breaker = {
    "failure_count": 0,
    "last_fail_time": 0.0,
    "threshold": 5,          # 5 次连续失败后熔断
    "cooldown": 60,          # 60 秒冷却期
}


def _circuit_ok() -> bool:
    cb = _circuit_breaker
    if cb["failure_count"] >= cb["threshold"]:
        if time.time() - cb["last_fail_time"] > cb["cooldown"]:
            cb["failure_count"] = 0  # 冷却后重置，给一次机会
            return True
        return False  # 熔断中
    return True


def _circuit_record_fail():
    cb = _circuit_breaker
    cb["failure_count"] += 1
    cb["last_fail_time"] = time.time()
    log.warning("LLM 熔断计数: %s/%s", cb["failure_count"], cb["threshold"])
    # 🟢 告警日志：第一次失败就记一条 warn
    if cb["failure_count"] == 1:
        try:
            from app.services import store
            store.log_alert("warn", "llm", "LLM 调用失败",
                            f"累计 {cb['failure_count']}/{cb['threshold']}，60s 后冷却")
        except Exception:
            pass
    # 触发熔断时记 critical
    if cb["failure_count"] >= cb["threshold"]:
        try:
            from app.services import store
            store.log_alert("critical", "llm", "LLM 熔断触发",
                            f"连续 {cb['failure_count']} 次失败，60s 内所有 LLM 调用将抛 LLMError 由上层降级")
        except Exception:
            pass


def _circuit_record_ok():
    _circuit_breaker["failure_count"] = 0


class LLMError(RuntimeError):
    pass


def _track_usage(usage: Any, caller: str, session_id: str = "",
                 model: str = "") -> None:
    """从 OpenAI resp.usage 提取 token 数并落库。任何异常静默。"""
    try:
        if not usage:
            return
        p = int(getattr(usage, "prompt_tokens", 0) or 0)
        c = int(getattr(usage, "completion_tokens", 0) or 0)
        if not (p or c):
            return
        cost = (p * settings.LLM_PRICE_INPUT_PER_M
                + c * settings.LLM_PRICE_OUTPUT_PER_M) / 1_000_000
        from app.services import store
        store.save_token_usage(model or settings.DEEPSEEK_MODEL, caller, p, c,
                               cost, session_id)
    except Exception:  # noqa: BLE001
        pass


def _get_client():
    """懒加载，避免没配 Key 时 import 就炸。"""
    global _client
    if _client is None:
        if not settings.has_llm:
            raise LLMError("未配置 DEEPSEEK_API_KEY")
        from openai import OpenAI
        _client = OpenAI(api_key=settings.DEEPSEEK_API_KEY,
                         base_url=settings.DEEPSEEK_BASE_URL, timeout=60)
    return _client


def chat(system: str, user: str, temperature: float = 0.2,
         json_mode: bool = False, max_retry: int = 2,
         caller: str = "unknown", session_id: str = "") -> str:
    """同步调用文本模型。json_mode=True 时强制返回 JSON 对象。

    内置保护：
    - 并发信号量（最多 3 个并行调用）
    - 指数退避重试（sleep 2^attempt 秒）
    - 熔断（5 次连续失败后 60 秒内直接抛 LLMError，由上层降级）
    - token 用量统计（caller 标记调用方，落 token_usage 表）
    """
    if not _circuit_ok():
        raise LLMError("LLM 熔断中（最近连续失败过多），请稍后重试")

    with _llm_semaphore:  # 🔒 P0-1 并发锁
        last: Exception | None = None
        for attempt in range(max_retry + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "temperature": temperature,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = _get_client().chat.completions.create(**kwargs)
                _circuit_record_ok()  # 成功 → 重置熔断
                _track_usage(getattr(resp, "usage", None), caller, session_id)
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:  # noqa: BLE001
                last = e
                _circuit_record_fail()  # 失败 → 熔断计数 +1
                log.warning("LLM 调用失败(%s/%s): %s", attempt + 1, max_retry + 1, e)
                _reset_client()
                if attempt < max_retry:
                    # 🔒 P0-2 指数退避: sleep 1s, 2s, 4s...
                    sleep_s = 2 ** attempt
                    log.info("指数退避 sleep %ss 后重试", sleep_s)
                    time.sleep(sleep_s)
    raise LLMError(f"文本模型调用失败: {last}")


def chat_json(system: str, user: str, default: dict,
             schema: dict | None = None,
             caller: str = "unknown", session_id: str = "") -> dict:
    """要 JSON 就用这个。

    🟢 P3-2: schema 校验
    - 传入 schema dict（如 {"required": ["level", "confidence", "advice"]}）
    - 模型输出必须包含所有 required 字段，否则重试 1 次
    - 两次都失败 → 返回 default（不让流程断）
    """
    last_err = None
    for attempt in range(2):  # 最多 2 次（1 次原调用 + 1 次 schema 校验失败重试）
        try:
            raw = chat(system, user, json_mode=True,
                       caller=caller, session_id=session_id)
            obj = json.loads(_strip_fence(raw))
            if schema:
                # 简单 required 字段校验
                missing = []
                for f in schema.get("required", []):
                    if f not in obj:
                        missing.append(f)
                if missing:
                    raise ValueError(f"schema 校验失败：缺字段 {missing}")
                # 类型检查（如果指定了 type）
                for f, expected_type in schema.get("types", {}).items():
                    if f in obj and not isinstance(obj[f], expected_type):
                        raise ValueError(f"schema 校验失败：{f} 应为 {expected_type.__name__}，实际 {type(obj[f]).__name__}")
            return obj
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("chat_json 第 %s 次解析/校验失败: %s", attempt + 1, e)
    log.warning("chat_json 两次失败，使用默认值: %s", last_err)
    return default


def chat_with_tools(system: str, user: str, tools: list, tool_choice: str = "auto",
                    max_iter: int = 3,
                    caller: str = "tools", session_id: str = "") -> tuple[str, list[dict]]:
    """带 function calling 的对话。

    - 用 chat.completions.create 传 tools + tool_choice，最多 max_iter 轮
    - 每轮若模型返回 tool_calls，就把工具结果以 role=tool 放回 messages，继续让模型出结论
    - 返回 (最终文本, 工具调用记录列表)；记录每项 {name, args, result(截断≤200字)}
    - 任何异常（provider 不支持 function calling / 网络失败）一律降级为普通 chat()，
      返回 (chat(...), [])，绝不把异常抛给上层
    """
    records: list[dict] = []
    try:
        from app.agent import tools as agent_tools  # 懒加载，避免 import 环
    except Exception:  # noqa: BLE001
        return chat(system, user, caller=caller, session_id=session_id), records

    try:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        final = ""
        for _ in range(max_iter):
            resp = _get_client().chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=0.2,
            )
            _track_usage(getattr(resp, "usage", None), caller, session_id)
            msg = resp.choices[0].message
            if not getattr(msg, "tool_calls", None):
                final = (msg.content or "").strip()
                break

            # 回填 assistant 消息（含 tool_calls），跨版本手工构造保证可序列化
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": t.id, "type": "function",
                     "function": {"name": t.function.name,
                                  "arguments": t.function.arguments}}
                    for t in msg.tool_calls
                ],
            })
            for t in msg.tool_calls:
                try:
                    args = json.loads(t.function.arguments or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                result = agent_tools.dispatch(t.function.name, args)
                records.append({"name": t.function.name, "args": args,
                                "result": (result or "")[:200]})
                messages.append({"role": "tool", "tool_call_id": t.id,
                                 "content": result})

        if not final:
            final = chat(system, user, caller=caller, session_id=session_id)
        return final, records
    except Exception as e:  # noqa: BLE001
        log.warning("工具调用失败，降级为普通 chat: %s", e)
        _reset_client()
        try:
            return chat(system, user, caller=caller, session_id=session_id), records
        except Exception:  # noqa: BLE001
            return "", records


def tool_loop(system: str, user: str, tools: list, max_rounds: int = 3,
              caller: str = "react", session_id: str = "") -> tuple[str, list[dict]]:
    """🟢 原生 Function Calling 自主循环（ReAct 模式）。

    每轮：模型判断 → 若返回 tool_calls 则 dispatch 执行并把结果回填 → 再判断。
    模型不再调工具即认为证据充分，此时其 content 作为结论。

    返回 (final_text, events)；events 每项:
      {"round": n, "type": "thought", "text": "模型未调工具，证据充分"}
      {"round": n, "type": "tool", "name": ..., "args": {...}, "observation": "结果≤200字"}
    任何异常都兜底返回 ("", events)，绝不抛出。
    """
    events: list[dict] = []
    try:
        from app.agent import tools as agent_tools
    except Exception:  # noqa: BLE001
        return "", events

    try:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        final = ""
        for round_num in range(1, max_rounds + 1):
            resp = _get_client().chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
            _track_usage(getattr(resp, "usage", None), caller, session_id)
            msg = resp.choices[0].message

            if not getattr(msg, "tool_calls", None):
                final = (msg.content or "").strip()
                events.append({"round": round_num, "type": "thought",
                               "text": "模型判断证据充分，未再调用工具"})
                break

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": t.id, "type": "function",
                     "function": {"name": t.function.name,
                                  "arguments": t.function.arguments}}
                    for t in msg.tool_calls
                ],
            })
            for t in msg.tool_calls:
                try:
                    args = json.loads(t.function.arguments or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                result = agent_tools.dispatch(t.function.name, args)
                events.append({"round": round_num, "type": "tool",
                               "name": t.function.name, "args": args,
                               "observation": (result or "")[:200]})
                messages.append({"role": "tool", "tool_call_id": t.id,
                                 "content": result})
        else:
            events.append({"round": max_rounds, "type": "thought",
                           "text": f"已达最大轮数 {max_rounds}，停止补充证据"})
        return final, events
    except Exception as e:  # noqa: BLE001
        log.warning("tool_loop 失败（返回已收集事件）: %s", e)
        _reset_client()
        return "", events


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _reset_client():
    global _client
    _client = None


def stream_chat(system: str, user: str, temperature: float = 0.3,
                caller: str = "stream", session_id: str = ""):
    """流式输出，用于 WebSocket 的打字机效果。"""
    if not _circuit_ok():
        yield chat(system, user, temperature=temperature,
                   caller=caller, session_id=session_id)
        return
    try:
        with _llm_semaphore:
            resp = _get_client().chat.completions.create(
                model=settings.DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature, stream=True,
                stream_options={"include_usage": True},
            )
            _circuit_record_ok()
            for chunk in resp:
                # 最后一个 chunk 只带 usage 不带 delta
                if getattr(chunk, "usage", None):
                    _track_usage(chunk.usage, caller, session_id)
                    continue
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
    except Exception as e:  # noqa: BLE001
        _circuit_record_fail()
        log.warning("流式调用失败，降级为整段输出: %s", e)
        yield chat(system, user, temperature=temperature,
                   caller=caller, session_id=session_id)
