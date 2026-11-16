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


class EvidenceCitationDraft(BaseModel):
    """An LLM citation that must resolve to text read by Fillo in this request."""

    evidence_id: str = Field(min_length=1, max_length=100)
    role: Literal["field", "value"]
    excerpt: str = Field(min_length=1, max_length=1000)


class FieldProposalDraft(BaseModel):
    field_name: str = Field(min_length=1, max_length=200)
    status: Literal["matched", "no_match", "ambiguous"]
    value: str | None = Field(default=None, max_length=4000)
    candidate_values: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceCitationDraft] = Field(default_factory=list, max_length=20)


class IntakeProposalDraft(BaseModel):
    fields: list[FieldProposalDraft] = Field(default_factory=list, max_length=100)


class ProposalEvidence(BaseModel):
    evidence_id: str
    role: Literal["field", "value"]
    source_type: Literal["web_screenshot", "document_page"]
    source_name: str
    page: int
    excerpt: str
    method: str | None = None
    confidence: float | None = None


class ProposedField(BaseModel):
    field_name: str
    status: Literal["matched", "no_match", "ambiguous"]
    value: str | None = None
    candidate_values: list[str] = Field(default_factory=list)
    evidence: list[ProposalEvidence] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)


class IntakeProposal(BaseModel):
    status: Literal["ready", "no_evidence", "failed"]
    fields: list[ProposedField] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
