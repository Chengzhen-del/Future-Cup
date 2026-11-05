"""API Key 诊断：定位 401 / 连不通的真实原因。

最常见的坑是**地域不匹配** —— 百炼各地域的 API Key 相互独立、不能跨地域使用。
在新加坡站建的 Key 调北京 endpoint，返回的就是 401 Incorrect API key。

用法：
    python scripts\\diagnose_key.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

# 百炼各地域的 OpenAI 兼容 endpoint
DASHSCOPE_ENDPOINTS = [
    ("华北2(北京)", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("新加坡", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    ("美国(弗吉尼亚)", "https://dashscope-us.aliyuncs.com/compatible-mode/v1"),
    ("北京·试用域名", "https://trial.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
    ("新加坡·试用域名", "https://trial.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"),
]

PROBE_MODEL = "qwen-plus"     # 最便宜的文本模型，只吐 8 个 token
TIMEOUT = 30.0


def probe(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """返回 (是否通过, 说明)。"""
    from openai import OpenAI
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复两个字：正常"}],
            max_tokens=8,
        )
        return True, (r.choices[0].message.content or "").strip()[:20]
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # 只留关键信息，别刷屏
        for line in msg.splitlines():
            if "Error code" in line or "错误码" in line:
                return False, line.strip()[:120]
        return False, msg.strip().splitlines()[0][:120] if msg else repr(e)


def main() -> int:
    print("=" * 64)
    print("智巡 InspectAgent · API Key 诊断")
    print("=" * 64)

    # ---------- DeepSeek ----------
    print("\n[1] DeepSeek 文本推理")
    if not settings.has_llm:
        print("    [未配置] .env 里 DEEPSEEK_API_KEY 是空的")
        print("    → 去 https://platform.deepseek.com/ 创建并充值后填入")
    else:
        ok, info = probe(settings.DEEPSEEK_BASE_URL, settings.DEEPSEEK_API_KEY,
                         settings.DEEPSEEK_MODEL)
        print(f"    {'[通过]' if ok else '[失败]'} {settings.DEEPSEEK_BASE_URL} → {info}")
        if not ok and ("402" in info or "Insufficient" in info or "余额" in info):
            print("    → 余额不足，去控制台充值 10 元即可")

    # ---------- DashScope ----------
    print("\n[2] Qwen-VL 视觉判读（百炼）")
    if not settings.has_vision:
        print("    [未配置] .env 里 DASHSCOPE_API_KEY 是空的")
        return 1

    key = settings.DASHSCOPE_API_KEY
    print(f"    Key：{key[:6]}…{key[-4:]}（长度 {len(key)}）")

    hit = None
    for name, url in DASHSCOPE_ENDPOINTS:
        ok, info = probe(url, key, PROBE_MODEL)
        flag = "[通过]" if ok else "[失败]"
        print(f"    {flag} {name:<14} {url}")
        print(f"           {info}")
        if ok and hit is None:
            hit = url

    print("\n" + "-" * 64)
    if hit:
        print(f"可用地域：{hit}")
        cur = settings.DASHSCOPE_BASE_URL.rstrip("/")
        if cur == hit.rstrip("/"):
            print("✅ .env 里的 DASHSCOPE_BASE_URL 已经是对的")
        else:
            print("⚠️  把 .env 改成：")
            print(f"    DASHSCOPE_BASE_URL={hit}")
    else:
        print("三个地域全部失败 —— 不是地域问题，是 Key 本身有问题：")
        print("  1. 确认在百炼控制台（bailian.console.aliyun.com）创建的是『API Key』，")
        print("     不是阿里云 AccessKey（LTAI 开头的那个）")
        print("  2. 确认已开通百炼大模型服务、模型在可用列表里")
        print("  3. 免费额度已用完也会报额度类错误，去『额度管理』看一眼")
        print("  4. 实在搞不定就换硅基流动：见 .env.example 里的备选方案 B")
    print("=" * 64)
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
