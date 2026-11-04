from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    MONGO_URI:str
    PORT:int
    db:str
    api_key: SecretStr
    allowed_source_roots: list[Path] = Field(default_factory=list)
    ocr_engine: Literal["tesseract", "claude"] = "tesseract"
    ocr_lang: str = "eng"                       # tesseract languages, e.g. "eng+urd"
    ocr_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("API_KEY must contain at least 32 characters")
        return value

settings = Settings()
