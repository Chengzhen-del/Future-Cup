"""大模型连通性自检：D2 必须跑通这两个调用。

用法：
    python scripts/test_llm.py
先复制 .env.example 为 .env 并填入 Key。
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.llm import LLMError, chat  # noqa: E402
from app.services.vision import analyze  # noqa: E402


def make_test_image() -> bytes:
    """生成一张纯色测试图，验证视觉链路能通（不依赖真实照片）。"""
    img = Image.new("RGB", (320, 240), (200, 120, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def main() -> int:
    print("=" * 60)
    print("智巡 InspectAgent · 大模型连通性自检")
    print("=" * 60)

    ok_text = False
    print("\n[1] DeepSeek 文本推理")
    print(f"    base_url = {settings.DEEPSEEK_BASE_URL}")
    print(f"    model    = {settings.DEEPSEEK_MODEL}")
    if not settings.has_llm:
        print("    [跳过] 未配置 DEEPSEEK_API_KEY")
    else:
        try:
            r = chat("你是助手，只回答数字。", "1+1等于几？只输出数字。")
            print(f"    [通过] 返回：{r[:40]}")
            ok_text = True
        except LLMError as e:
            print(f"    [失败] {e}")

    ok_vision = False
    print("\n[2] Qwen-VL 视觉判读")
    print(f"    base_url = {settings.DASHSCOPE_BASE_URL}")
    print(f"    model    = {settings.QWEN_VL_MODEL}")
    if not settings.has_vision:
        print("    [跳过] 未配置 DASHSCOPE_API_KEY")
    else:
        try:
            data = analyze(make_test_image(), "这是一张测试图")
            if data.get("error"):
                print(f"    [失败] {data['error'][:120]}")
            else:
                print(f"    [通过] scene = {str(data.get('scene'))[:40]}")
                ok_vision = True
        except Exception as e:  # noqa: BLE001
            print(f"    [失败] {e}")

    print("\n" + "=" * 60)
    print(f"结果：文本 {'OK' if ok_text else '未通过'} ｜ 视觉 {'OK' if ok_vision else '未通过'}")
    if not (ok_text or ok_vision):
        print("两个都没通 -> 当前为 MOCK 模式，端侧可联调但演示不是真智能体。")
        print("处理：检查 Key 是否正确、余额是否充足、网络是否可达；超过一天就换供应商。")
    print("=" * 60)
    return 0 if (ok_text and ok_vision) else 1


if __name__ == "__main__":
    sys.exit(main())
