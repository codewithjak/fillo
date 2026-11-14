from typing import Literal

from pydantic import BaseModel, Field


class GoalPlan(BaseModel):
    """A structured summary of the user's intended outcome."""

    action: Literal["fill", "create", "extract", "inspect", "other"] = Field(
        description=(
            "The intended operation: fill an existing online form, create a new "
            "online record, extract information, inspect a resource, or other/unclear."
        )
    )
    target_record: str = Field(
        min_length=1,
        max_length=200,
        description="The form, application, document, or record the user wants handled.",
    )
    needed_evidence: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Kinds of information needed to reach the requested outcome.",
    )
    expected_result: str = Field(
        min_length=1,
        max_length=500,
        description="The concrete result Fillo should prepare for the user.",
    )
