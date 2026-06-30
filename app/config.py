from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
import os


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Settings(BaseModel):
    app_name: str = "LabScribe Agent"
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    baidu_app_id: str = os.getenv("BAIDU_APP_ID", "0")
    baidu_api_key: str = os.getenv("BAIDU_API_KEY", "")
    baidu_secret_key: str = os.getenv("BAIDU_SECRET_KEY", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    data_dir: Path = ROOT / os.getenv("DATA_DIR", "data")
    database_path: Path = ROOT / os.getenv("DATABASE_PATH", "data/report_assistant.db")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "30"))

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "outputs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for path in (settings.data_dir, settings.upload_dir, settings.output_dir):
        path.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings

