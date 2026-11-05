"""模型探针：逐个试候选模型，输出「哪个真能跑」。

方舟模型多且迭代快，列表里有的名字不一定能直接调（有的要接入点、有的要开通）。
与其猜，不如逐个打一发最小请求。

用法：
    python scripts\\probe_models.py
"""
import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
from openai import OpenAI  # noqa: E402

from app.config import settings  # noqa: E402

TEXT_CANDIDATES = [
    "doubao-seed-2-1-pro-260915",
    "doubao-seed-2-1-lite-260915",
    "doubao-seed-1-6-250615",
    "doubao-seed-1-6-flash-250828",
    "deepseek-v4-pro-ga-260813",
    "deepseek-v4-1-flash-261017",
    "deepseek-v3-2-251201",
]

VISION_CANDIDATES = [
    "doubao-seed-1-6-vision-250815",
    "doubao-1.5-vision-pro-250328",
    "doubao-1-5-vision-pro-32k-250115",
    "doubao-1-5-thinking-vision-pro-250428",
    "doubao-vision-pro-32k-241028",
]

TIMEOUT = 45.0


def make_image_b64() -> str:
    img = Image.new("RGB", (240, 180), (190, 110, 55))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def err_line(e: Exception) -> str:
    msg = str(e)
    for line in msg.splitlines():
        if "Error code" in line or "错误" in line:
            return line.strip()[:110]
    return msg.strip().splitlines()[0][:110] if msg else repr(e)


def probe(client: OpenAI, model: str, with_image: bool = False) -> tuple[bool, str]:
    try:
        if with_image:
            content = [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{make_image_b64()}"}},
                {"type": "text", "text": "一句话描述这张图，不超过15字"},
            ]
        else:
            content = "只回复两个字：正常"
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_tokens=16,
            timeout=TIMEOUT,
        )
        return True, (r.choices[0].message.content or "").strip()[:24]
    except Exception as e:  # noqa: BLE001
        return False, err_line(e)


def main() -> int:
    base = settings.DEEPSEEK_BASE_URL
    key = settings.DEEPSEEK_API_KEY
    if not key:
        print("没有 Key")
        return 1

    client = OpenAI(api_key=key, base_url=base, timeout=TIMEOUT)

    # 命令行可以指定要测的模型：
    #   python scripts\probe_models.py ep-xxx-1 ep-xxx-2      # 当文本测
    #   python scripts\probe_models.py --vision ep-xxx-1      # 当视觉测
    args = sys.argv[1:]
    only_vision = "--vision" in args
    custom = [a for a in args if not a.startswith("--")]
    text_list = custom if (custom and not only_vision) else TEXT_CANDIDATES
    vision_list = custom if (custom and only_vision) else VISION_CANDIDATES

    print("=" * 66)
    print(f"供应商 base_url = {base}")
    print("=" * 66)

    print("\n[文本模型]（挑 1 个通的最快的）")
    ok_text = []
    for m in text_list:
        ok, info = probe(client, m)
        print(f"    {'✔' if ok else '✘'} {m:<34} {info}")
        if ok:
            ok_text.append(m)

    print("\n[视觉模型]（挑 1 个通的）")
    ok_vision = []
    for m in vision_list:
        ok, info = probe(client, m, with_image=True)
        print(f"    {'✔' if ok else '✘'} {m:<34} {info}")
        if ok:
            ok_vision.append(m)

    print("\n" + "-" * 66)
    print("建议写进 .env：")
    if ok_text:
        print(f"    DEEPSEEK_MODEL={ok_text[0]}      # 备选 {ok_text[1] if len(ok_text)>1 else '无'}")
    else:
        print("    DEEPSEEK_MODEL=?  （全挂 —— 去控制台给模型建『推理接入点』，填 ep- 开头的 ID）")
    if ok_vision:
        print(f"    QWEN_VL_MODEL={ok_vision[0]}")
    else:
        print("    QWEN_VL_MODEL=?  （全挂 —— 同上，建接入点）")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
