import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.intake import run_intake_agent
from app.config import settings
from app.ingestion.service import SourcePathError, resolve_allowed_source_root
from app.schema.index import AgentIntakeInput, AgentIntakeOutput
from app.security import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/agent",
    tags=["agent"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/intake", response_model=AgentIntakeOutput)
async def agentic_intake(body: AgentIntakeInput, request: Request) -> AgentIntakeOutput:
    if not settings.anthropic_api_key:
        raise HTTPException(503, "The intake agent is unavailable; configure ANTHROPIC_API_KEY")

    source_path = None
    if body.source_path is not None:
        try:
            source_path = str(resolve_allowed_source_root(body.source_path))
        except SourcePathError as e:
            raise HTTPException(e.status_code, e.detail) from e

    run_id = uuid.uuid4().hex
    activity: list[dict] = []
    try:
        response = await run_intake_agent(
            url=str(body.url),
            goal=body.goal,
            source_path=source_path,
            schedule_job=request.app.state.schedule_job,
            activity=activity,
        )
    except Exception as e:
        logger.exception("Agent intake run %s failed", run_id)
        raise HTTPException(502, "The intake agent could not complete this request") from e

    return AgentIntakeOutput(run_id=run_id, response=response, tool_activity=activity)
