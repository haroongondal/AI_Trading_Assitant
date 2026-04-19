"""
Pydantic request/response schemas. JS parallel: like Zod + TypeScript interfaces.
"""
from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    model_id: str | None = None


class PortfolioPositionCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    quantity: float = Field(..., gt=0)
    entry_price: float | None = Field(default=None, gt=0)  # optional; 0 used when omitted for analysis
    notes: str | None = None


class PortfolioPositionUpdate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    entry_price: float | None = Field(default=None, gt=0)
    notes: str | None = None


class PortfolioGoalUpdate(BaseModel):
    goal: str | None = None


class PortfolioPositionOut(BaseModel):
    id: int
    symbol: str
    quantity: float
    entry_price: float
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortfolioOut(BaseModel):
    positions: list[PortfolioPositionOut]
    total_positions: int
    goal: str | None = None


class NotificationOut(BaseModel):
    id: int
    title: str
    body: str
    suggested_action: str | None
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationRead(BaseModel):
    read: bool = True


class UserOut(BaseModel):
    id: str
    name: str
    email: str | None = None
