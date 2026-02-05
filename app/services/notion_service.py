from notion_client import Client
from datetime import datetime, timedelta, timezone

from app.models import NotionPage, NotionData
from app.config import settings
from app.logger import setup_logger

logger = setup_logger(__name__)


class NotionService:
    def __init__(self):
        self.client = Client(auth=settings.notion_api_key)
        logger.info("✅ Notion service ready")

    def query_database(self, database_id: str) -> NotionData:
        """Get pages from a database"""
        logger.info(f"Querying: {database_id}")
        results = self.client.databases.query(database_id=database_id)
        pages = self._parse_pages(results.get("results", [])[:15])
        return NotionData(pages=pages, total_count=len(pages), database_id=database_id)

    def search_pages(self, query: str) -> NotionData:
        """Search across workspace"""
        logger.info(f"Searching: {query}")
        results = self.client.search(query=query).get("results", [])[:10]
        pages = self._parse_pages([r for r in results if r["object"] == "page"])
        return NotionData(pages=pages, total_count=len(pages), database_id="search")

    def get_updates(self, database_id: str, hours: int = 24) -> NotionData:
        """Get recently updated pages"""
        logger.info(f"Getting updates from last {hours}h")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        results = self.client.databases.query(
            database_id=database_id,
            filter={
                "timestamp": "last_edited_time",
                "last_edited_time": {"after": cutoff.isoformat()},
            },
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        )
        pages = self._parse_pages(results.get("results", [])[:10])
        return NotionData(pages=pages, total_count=len(pages), database_id=database_id)

    def get_page_content(self, page_id: str) -> str:
        """Get text content from a page"""
        logger.info(f"Fetching content: {page_id}")
        blocks = self.client.blocks.children.list(block_id=page_id)

        texts = []
        for block in blocks.get("results", []):
            block_type = block.get("type")
            data = block.get(block_type, {})
            if "rich_text" in data:
                text = "".join(t.get("plain_text", "") for t in data["rich_text"])
                texts.append(text)

        return "\n".join(texts)

    def _parse_pages(self, results: list) -> list[NotionPage]:
        """Convert API results into NotionPage objects"""
        pages = []
        for r in results:
            pages.append(
                NotionPage(
                    page_id=r["id"],
                    title=self._get_title(r),
                    properties=r.get("properties", {}),
                    updated_at=datetime.fromisoformat(r["last_edited_time"]),
                    created_at=datetime.fromisoformat(r["created_time"]),
                    url=r.get("url"),
                )
            )
        return pages

    def _get_title(self, page: dict) -> str:
        """Extract title from page properties"""
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                return "".join(t.get("plain_text", "") for t in prop.get("title", []))
        return "Untitled"

    def health_check(self) -> bool:
        try:
            self.client.users.me()
            return True
        except Exception:
            return False


notion_service = NotionService()
