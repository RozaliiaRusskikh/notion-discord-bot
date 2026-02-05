from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ActionType(str, Enum):
    STATUS = "status"
    SEARCH = "search"
    LIST = "list"
    UPDATES = "updates"
    SUMMARY = "summary"


class NotionPage(BaseModel):
    page_id: str
    title: str
    properties: dict
    updated_at: datetime
    created_at: datetime
    url: str | None = None
    content: str | None = None


class NotionData(BaseModel):
    pages: list[NotionPage]
    total_count: int
    database_id: str


class Command(BaseModel):
    user_id: str
    action: ActionType
    target: str
    query: str | None = None
    original_message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class BotResponse(BaseModel):
    content: str
    pages_analyzed: int
    success: bool = True
    error: str | None = None


class HealthCheck(BaseModel):
    status: str
    discord: bool
    notion: bool
    ai: bool