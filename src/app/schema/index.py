from pathlib import Path

from pydantic import BaseModel, field_validator


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
