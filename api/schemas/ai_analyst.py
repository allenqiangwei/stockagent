"""AI Analyst Pydantic schemas — request/response models."""

from typing import Optional
from pydantic import BaseModel


# -- Reports ------------------------------------------------

class AIReportResponse(BaseModel):
    id: int
    report_date: str
    report_type: str
    market_regime: Optional[str] = None
    market_regime_confidence: Optional[float] = None
    recommendations: Optional[list] = None
    strategy_actions: Optional[list] = None
    thinking_process: str
    summary: str
    created_at: str

    model_config = {"from_attributes": True}


class AIReportListItem(BaseModel):
    id: int
    report_date: str
    report_type: str
    market_regime: Optional[str] = None
    summary: str
    created_at: str

    model_config = {"from_attributes": True}


# -- Chat ---------------------------------------------------

class AIReportSaveRequest(BaseModel):
    report_date: str
    report_type: str = "daily"
    market_regime: Optional[str] = None
    market_regime_confidence: Optional[float] = None
    recommendations: Optional[list] = None
    strategy_actions: Optional[list] = None
    thinking_process: str = ""
    summary: str = ""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class ChatSessionResponse(BaseModel):
    id: int
    session_id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
