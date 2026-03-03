"""
Pydantic models for API requests and responses
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal
from enum import Enum
import re

from pydantic import BaseModel, Field, validator


class MessagePayload(BaseModel):
    """Message payload structure — minimal, no redundant fields."""
    response: str
    needs_location: bool = Field(default=False, description="Flag to trigger external GPS/map picker")
    chat_locked: bool = Field(default=False, description="Flag indicating chat is locked and user must start a new chat")


class ChatRequest(BaseModel):
    """Chat request model"""
    chat_id: Optional[str] = Field(default=None, description="User identifier")
    session_id: Optional[str] = Field(default=None, description="Session ID from previous response")
    message: str = Field(..., min_length=1, max_length=5000)
    location: Optional[dict] = Field(default=None, description="GPS location from external map picker")

    @validator("chat_id", "session_id")
    def validate_ids(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v or len(v) > 255:
            raise ValueError("Invalid ID length")
        if not re.match(r"^[a-zA-Z0-9_:-]+$", v):
            raise ValueError("ID has invalid characters")
        return v

    @validator("message")
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        if len(v) > 5000:
            v = v[:5000] + "..."
        return v


class ChatResponse(BaseModel):
    """Chat response model"""
    session_id: str = Field(description="Full session ID")
    chat_message_id: Optional[str] = None
    created: datetime
    message: MessagePayload
    suggested_answers: List[str] = Field(default=[], description="Quick reply options for the user to tap")
    chat_message_type: Literal["Assistant"] = "Assistant"
    awaitingConfirmation: bool = False


class ChatHistoryMessage(BaseModel):
    """Chat history message model"""
    chat_message_id: str
    created: datetime
    message: Any
    role: Literal["user", "assistant"]


class PaginationInfo(BaseModel):
    """Pagination information"""
    total: int
    page: int
    size: int
    pages: int


class ChatHistoryResponse(BaseModel):
    """Chat history response model"""
    session_id: str
    messages: List[ChatHistoryMessage]
    pagination: PaginationInfo


class UpdateTitleRequest(BaseModel):
    """Update title request model"""
    chat_id: Optional[str] = None
    session_id: Optional[str] = None
    title: str = Field(..., min_length=1)


class UpdateTitleResponse(BaseModel):
    """Update title response model"""
    session_id: str
    title: str
    message: str = "Title updated."


class ChatMessagesRequest(BaseModel):
    """Chat messages request model"""
    ChatId: str
    SessionId: Optional[str] = None


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorResponse(BaseModel):
    error: bool = True
    code: ErrorCode
    message: str
    request_id: Optional[str] = None
    details: Optional[dict] = None
