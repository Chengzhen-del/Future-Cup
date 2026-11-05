"""方舟视觉接入点一键配置脚本（Windows / Python 3.11）

用法（在 D:\\code\\inspectagent-cloud 目录下）：

    .\\.venv\\Scripts\\python.exe scripts\\setup_vision.py ep-20251xxxx-xxxxx

或者不带参数直接跑，脚本会提示你把 ep- ID 粘贴进来：

    .\\.venv\\Scripts\\python.exe scripts\\setup_vision.py

脚本会做三件事：
    1. 现造一张测试图（模拟配电柜指示灯 + 仪表），不依赖 Pillow、不联网下载
    2. 用真实巡检 prompt 调一次视觉模型，验证接入点是不是真的能看图
    3. 验证通过 -> 自动把 QWEN_VL_MODEL 写进 .env（其它配置行原样保留）

退出码：0 = 成功并已写入；1 = 验证失败；2 = 用法/环境问题。
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from testimg import make_test_image  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass


# ---------------------------------------------------------------- 视觉验证

PROMPT = (
    "你是电力巡检视觉判读助手。观察这张配电柜照片，只输出 JSON，不要任何解释文字：\n"
    '{"findings":[{"item":"部件名","status":"正常|异常|未见","desc":"简述","risk":"无|低|中|高"}],'
    '"summary":"一句话结论"}'
)


def call_vision(model_id: str, img_b64: str) -> tuple[bool, str]:
    from openai import OpenAI  # 延迟导入，报错信息更干净

    from app.config import settings

    client = OpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.DASHSCOPE_BASE_URL,
        timeout=90,
    )
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        max_tokens=600,
    )
    return True, (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------- 写回 .env

def write_env(model_id: str) -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"✗ 找不到 {env_path}，请手动把 QWEN_VL_MODEL={model_id} 写进 .env")
        return
    text = env_path.read_text(encoding="utf-8")
    new_line = f"QWEN_VL_MODEL={model_id}"
    if re.search(r"^QWEN_VL_MODEL=.*$", text, flags=re.M):
        text = re.sub(r"^QWEN_VL_MODEL=.*$", new_line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + new_line + "\n"
    env_path.write_text(text, encoding="utf-8")
    print(f"✔ 已写入 .env -> {new_line}")


# ---------------------------------------------------------------- main

def main() -> int:
    print("=" * 64)
    print("智巡 InspectAgent · 方舟视觉接入点配置")
    print("=" * 64)

    model_id = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not model_id:
        print("\n把控制台里那串 ep- 开头的接入点 ID 粘到这里，回车：")
        print("（长这样：ep-20251031xxxxxx-abcde）\n")
        model_id = input("接入点 ID > ").strip()

    if not model_id:
        print("✗ 没拿到 ID")
        return 2

    print(f"\n[1/3] 生成测试图 ... 模型 = {model_id}")
    img_b64 = base64.b64encode(make_test_image()).decode("ascii")
    print(f"      测试图 {len(img_b64)} 字符(base64)")

    print("[2/3] 调用视觉模型判读 ...")
    try:
        ok, content = call_vision(model_id, img_b64)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"\n✗ 调用失败：{msg[:400]}")
        print("\n常见原因：")
        if "404" in msg or "does not exist" in msg:
            print("  · 这个模型还没开通 -> 控制台「模型广场」搜索模型名，点「开通」")
            print("  · 或者你填的是模型名而不是 ep- 接入点 ID -> 用接入点 ID 再试")
        elif "403" in msg or "not activated" in msg:
            print("  · 模型未开通 / 没同意服务协议 -> 去控制台开通")
        elif "401" in msg:
            print("  · API Key 不对或地域不对 -> 确认是华北(北京)，Key 没复制全")
        elif "429" in msg or "quota" in msg.lower():
            print("  · 额度用完了 -> 去控制台看余额")
        else:
            print("  · 接入点可能还在「调度中」，等 1-2 分钟状态变「健康」再试")
        return 1

    if not ok or not content:
        print("✗ 模型返回空内容（方舟个别推理模型会这样，换一个模型试试）")
        return 1

    print("[3/3] 模型返回：")
    print("-" * 64)
    print(content[:800])
    print("-" * 64)

    # 尽力解析 JSON，确认格式能用在业务里
    parsed = None
    m = re.search(r"\{.*\}", content, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            parsed = None
    if parsed and isinstance(parsed.get("findings"), list):
        print(f"✔ JSON 解析成功，findings 共 {len(parsed['findings'])} 条")
    else:
        print("⚠ 返回的不是严格 JSON，业务层有兜底解析，但建议换更稳的模型")

    write_env(model_id)
    print("\n下一步：重启服务后跑 python scripts\\smoke.py，"
          "看到「视觉判读」有 findings 就说明真通了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
