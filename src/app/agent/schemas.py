from typing import Any, Literal

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


class FormLocator(BaseModel):
    strategy: Literal["label", "id", "name", "test_id"]
    value: str
    unique: bool
    control_type: str | None = None


class FormOption(BaseModel):
    label: str
    value: str
    disabled: bool = False


class InspectedFormField(BaseModel):
    field_id: str
    label: str | None = None
    placeholder: str | None = None
    tag: str
    type: str
    role: str | None = None
    name: str | None = None
    group_name: str | None = None
    required: bool = False
    disabled: bool = False
    read_only: bool = False
    fillable: bool = True
    options: list[FormOption] = Field(default_factory=list)
    options_truncated: bool = False
    constraints: dict[str, Any] = Field(default_factory=dict)
    locators: list[FormLocator] = Field(default_factory=list)


class FormInspection(BaseModel):
    status: Literal["completed", "partial", "no_controls", "not_applicable"]
    fields: list[InspectedFormField] = Field(default_factory=list)
    truncated: bool = False
    embedded_frame_count: int = 0
    notes: list[str] = Field(default_factory=list)
