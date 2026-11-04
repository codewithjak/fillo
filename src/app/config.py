from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    MONGO_URI:str
    PORT:int
    db:str
    ocr_engine: Literal["tesseract", "claude"] = "tesseract"
    ocr_lang: str = "eng"                       # tesseract languages, e.g. "eng+urd"
    ocr_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None

settings = Settings()