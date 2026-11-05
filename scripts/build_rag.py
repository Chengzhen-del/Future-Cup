"""手动构建向量索引（可选）。

默认用的是关键词检索，**不需要跑这个脚本**。
只有当规范条目多到关键词匹配不够准（比如 >100 条）时才上向量库。

注意：首次运行 chromadb 会联网下载约 80MB 的 ONNX 模型，网差会很慢。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import rag  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    n = rag.build_index()
    if n:
        print(f"索引构建完成：{n} 条，用时 {time.time() - t0:.1f}s")
        print("然后在 .env 里设 RAG_ENABLED=1 并重启服务即可启用向量检索。")
    else:
        print("构建失败或 chromadb 不可用 —— 不影响主流程，服务仍会用关键词检索。")
