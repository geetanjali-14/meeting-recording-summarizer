import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DecisionConfidence(StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"


class TopicOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(description="Short topic heading (2-6 words)")
    summary: str = Field(description="1-3 sentence summary of topic discussion")
    sequence_index: int = 0
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision_text: str = Field(description="Summary of the decision made")
    confidence: DecisionConfidence = Field(default=DecisionConfidence.EXPLICIT)
    sequence_index: int = 0
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class ActionItemOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action_text: str = Field(description="Concrete task or follow-up action")
    owner: str | None = Field(default=None)
    due_date: str | None = Field(default=None)
    sequence_index: int = 0
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class RiskOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    risk_text: str = Field(description="Description of the risk or obstacle")
    sequence_index: int = 0
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class OpenQuestionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_text: str = Field(description="Unresolved inquiry from discussion")
    sequence_index: int = 0
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class MeetingAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = Field(default=None)
    executive_summary: str = Field(description="3-5 sentence factual executive summary")
    topics: list[TopicOutput] = Field(default_factory=list)
    decisions: list[DecisionOutput] = Field(default_factory=list)
    action_items: list[ActionItemOutput] = Field(default_factory=list)
    risks: list[RiskOutput] = Field(default_factory=list)
    open_questions: list[OpenQuestionOutput] = Field(default_factory=list)


# API response schemas for GET /api/v1/meetings/{id}/analysis
class TopicResponse(BaseModel):
    topic_id: uuid.UUID
    sequence_index: int
    title: str
    summary: str | None = None
    start_time: float | None = None
    end_time: float | None = None


class DecisionResponse(BaseModel):
    decision_id: uuid.UUID
    sequence_index: int
    decision_text: str
    confidence: DecisionConfidence
    start_time: float | None = None
    end_time: float | None = None
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class ActionItemResponse(BaseModel):
    action_item_id: uuid.UUID
    sequence_index: int
    action_text: str
    owner: str | None = None
    due_date: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class RiskResponse(BaseModel):
    risk_id: uuid.UUID
    sequence_index: int
    risk_text: str
    start_time: float | None = None
    end_time: float | None = None
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class OpenQuestionResponse(BaseModel):
    question_id: uuid.UUID
    sequence_index: int
    question_text: str
    start_time: float | None = None
    end_time: float | None = None
    evidence_segment_ids: list[uuid.UUID] = Field(default_factory=list)


class MeetingAnalysisResponse(BaseModel):
    analysis_id: uuid.UUID
    title: str | None = None
    executive_summary: str | None = None
    model: str
    estimated_cost_usd: float | None = None
    topics: list[TopicResponse] = Field(default_factory=list)
    decisions: list[DecisionResponse] = Field(default_factory=list)
    action_items: list[ActionItemResponse] = Field(default_factory=list)
    risks: list[RiskResponse] = Field(default_factory=list)
    open_questions: list[OpenQuestionResponse] = Field(default_factory=list)
