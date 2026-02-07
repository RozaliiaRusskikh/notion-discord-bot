from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ActionType(str, Enum):
    SEARCH = "search"  # Find by title/keyword
    LIST = "list"  # All pages, newest first
    UPDATES = "updates"  # Same as list, but emphasizing "recently edited"
    SUMMARY = "summary"  # Deep dive into one page content


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


class Command(BaseModel):
    user_id: str
    action: ActionType
    target: str
    query: str | None = None
    original_message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthCheck(BaseModel):
    status: str
    discord: bool
    notion: bool
    ai: bool
    github: bool