import re
from pydantic import BaseModel, field_validator
from pathlib import PurePosixPath

PATH_RE = re.compile(r"/(?:[\w.\-() ]+/)*[\w.\-() ]+/?")

class DocOutput(BaseModel):
    source_id: str
    job_id: str
    total: int
    status: str = "pending"

class DocInput(BaseModel):
    url:str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v:str) -> str:
        v = v.strip()
        if not PATH_RE.full_match(v):
            raise ValueError("url must be an absolute folder path, e.g. /home/user/docs")
        elif(".." in PurePosixPath(v).parts):
            raise ValueError("'..' is not allowed in the path")
        else:
            return v
    
