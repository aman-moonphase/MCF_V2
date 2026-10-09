from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    why_it_matters: str
    fields: List[str]
    status: str  # open | answered | resolved
    answer: Optional[str] = None
    answered_at: Optional[str] = None
    asked_at: Optional[str] = None


class ProductResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    understanding_status: str
    profile: Optional[Dict[str, Any]] = None
    clarification_questions: List[ClarificationQuestion] = []
    edited_fields: List[str] = []
    profile_version: int
    approved_version: Optional[int] = None
    approved_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    project_ids: List[UUID] = []


class ClarificationAnswer(BaseModel):
    question_id: str
    answer: str = Field(max_length=4000)


class SubmitAnswersRequest(BaseModel):
    project_id: UUID
    answers: List[ClarificationAnswer] = Field(min_length=1, max_length=10)


class UpdateProfileRequest(BaseModel):
    profile: Dict[str, Any]


class ApproveProfileRequest(BaseModel):
    project_id: UUID
    profile_version: int


class LinkProductRequest(BaseModel):
    product_id: UUID
