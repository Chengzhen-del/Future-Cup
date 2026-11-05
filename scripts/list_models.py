"""列出当前 Key 能访问的模型 / 接入点（任何 OpenAI 兼容供应商通用）。

方舟必须用这个脚本 —— 它的 model 参数要填「推理接入点 ID」（ep- 开头），
不查一下根本猜不出来。

用法：
    python scripts\\list_models.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

CANDIDATES = [
    ("华北(北京)", "https://ark.cn-beijing.volces.com/api/v3"),
    ("亚太(新加坡)", "https://ark.ap-southeast.volces.com/api/v3"),
]
TIMEOUT = 20


def fetch(base_url: str, key: str) -> tuple[int, str]:
    url = f"{base_url.rstrip('/')}/models?page_num=1&page_size=100"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:  # noqa: F821
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def main() -> int:
    key = settings.DEEPSEEK_API_KEY or settings.DASHSCOPE_API_KEY
    if not key:
        print("没有 Key：先在 .env 里填 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY")
        return 1

    print("=" * 62)
    print(f"Key：{key[:12]}…{key[-6:]}")
    print("=" * 62)

    for name, base in CANDIDATES:
        code, body = fetch(base, key)
        print(f"\n[{name}] {base}  ->  HTTP {code}")
        if code != 200:
            print(f"    {body[:200]}")
            continue
        try:
            data = json.loads(body).get("data", [])
        except Exception:  # noqa: BLE001
            print("    返回不是 JSON：", body[:200])
            continue
        if not data:
            print("    ⚠️ 列表为空 —— 需要在控制台创建『推理接入点』")
            continue
        for m in data:
            mid = m.get("id", "")
            tag = "【接入点】" if mid.startswith("ep-") else "【模型】"
            print(f"    {tag} {mid}")
    print("\n" + "=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
