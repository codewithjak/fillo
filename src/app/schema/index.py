from pathlib import Path

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class DocOutput(BaseModel):
    source_id: str
    job_id: str
    total: int
    status: str = "pending"


class SourceInput(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("path must be an absolute folder path")
        return str(path)


class AgentIntakeInput(BaseModel):
    url: HttpUrl
    goal: str = Field(
        default="Inspect this link and prepare its contents for document intake.",
        min_length=1,
        max_length=1000,
    )
    source_path: str | None = None

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("source_path must be an absolute folder path")
        return str(path)


class AgentToolActivity(BaseModel):
    tool: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentIntakeOutput(BaseModel):
    run_id: str
    response: str
    tool_activity: list[AgentToolActivity]
