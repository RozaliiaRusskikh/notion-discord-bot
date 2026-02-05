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
    """A single page from Notion"""

    page_id: str
    title: str
    properties: dict
    updated_at: datetime
    created_at: datetime
    url: str | None = None
    content: str | None = None


class NotionData(BaseModel):
    """Data returned from Notion query"""

    pages: list[NotionPage]
    total_count: int
    database_id: str


class Command(BaseModel):
    """Parsed Discord command"""

    user_id: str
    action: ActionType
    target: str
    query: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class BotResponse(BaseModel):
    """Response to send to Discord"""

    content: str
    pages_analyzed: int
    timestamp: datetime
    success: bool = True
    error: str | None = None


class HealthCheck(BaseModel):
    """API health status"""

    status: str
    discord: bool
    notion: bool
    ai: bool
    last_checked: datetime = Field(default_factory=datetime.now)
