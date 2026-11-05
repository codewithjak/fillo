from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ingestion.service import SourcePathError, register_source_root, resolve_allowed_source_root
from app.schema.index import DocOutput, SourceInput
from app.security import require_api_key

router = APIRouter(
    prefix="/api/v1/sources",
    tags=["fillo"],
    dependencies=[Depends(require_api_key)],
)

@router.post("", response_model=DocOutput, status_code=status.HTTP_202_ACCEPTED)
async def create_source(body: SourceInput, request: Request) -> DocOutput:
    try:
        root = resolve_allowed_source_root(body.path)
        result = await register_source_root(root, request.app.state.schedule_job)
    except SourcePathError as e:
        raise HTTPException(e.status_code, e.detail) from e
    return DocOutput(**result)
