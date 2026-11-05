"""全局配置：所有开关集中在这里，端侧同学只需看 api.md，不用读代码。"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# .env 只在本地生效；Docker 里由 environment 注入
load_dotenv(BASE_DIR / ".env", override=False)


class Settings:
    """轻量配置对象（不引第三方 settings 库，少一个依赖少一个坑）。"""

    APP_ENV: str = os.getenv("APP_ENV", "dev")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # ---- 大模型 ----
    # DeepSeek：文本推理 / 规划 / 决策（OpenAI 协议）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ---- Embedding / RAG ----
    # 自定 OpenAI 协议 embedding（方舟 /embeddings）；EMBEDDING_MODEL 留空则用
    # Chroma 内置默认 embedding（all-MiniLM-L6-v2 ONNX，无需 key）。
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "") or os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # 通义千问 Qwen-VL：视觉判读（百炼 OpenAI 兼容模式）
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    QWEN_VL_MODEL: str = os.getenv("QWEN_VL_MODEL", "qwen-vl-max-latest")

    # ---- 存储 ----
    DB_PATH: Path = DATA_DIR / "inspect.db"
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    CHROMA_DIR: Path = DATA_DIR / "chroma"

    # ---- 行为开关 ----
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))

    # ---- 登录鉴权（P0-3，默认开启） ----
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "1").lower() in ("1", "true")
    ACCESS_TOKEN_TTL_MIN: int = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "120"))
    REFRESH_TOKEN_TTL_DAYS: int = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "7"))

    # ---- Token 计费（元 / 百万 tokens，DeepSeek 官方价，可按需改） ----
    LLM_PRICE_INPUT_PER_M: float = float(os.getenv("LLM_PRICE_INPUT_PER_M", "2.0"))
    LLM_PRICE_OUTPUT_PER_M: float = float(os.getenv("LLM_PRICE_OUTPUT_PER_M", "8.0"))

    # 向量检索默认关闭：首次启用 chromadb 会联网下载 ~80MB 的 ONNX 模型，
    # 网差时会把启动卡死。默认走关键词检索，效果够演示，随时可开。
    RAG_ENABLED: bool = os.getenv("RAG_ENABLED", "0").lower() in ("1", "true")

    # 视觉判读模式：single=单次综合判读（快，默认）；multi=四工具精细判读
    # （慢，多 Agent 演示时开，一次巡检多 3 次 VLM 调用）
    VISION_MODE: str = os.getenv("VISION_MODE", "single")

    @property
    def has_llm(self) -> bool:
        return bool(self.DEEPSEEK_API_KEY)

    @property
    def has_vision(self) -> bool:
        return bool(self.DASHSCOPE_API_KEY)

    @property
    def mock_mode(self) -> bool:
        """没配 Key 就自动降级为 mock，保证端侧永远有返回值可联调。"""
        return os.getenv("MOCK_MODE", "").lower() in ("1", "true") or not (
            self.has_llm or self.has_vision
        )


settings = Settings()
settings.UPLOAD_DIR.mkdir(exist_ok=True)
