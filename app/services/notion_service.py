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

    def search_by_keyword(self, query: str) -> NotionData:
        """Search pages by keyword"""
        logger.info(f"Searching: {query}")
        results = self.client.search(query=query, page_size=15).get("results", [])
        pages = self._parse_pages(results)
        return NotionData(pages=pages, total_count=len(pages))

    def get_recent_updates(self, hours: int = 24) -> NotionData:
        """Get recently edited pages"""
        logger.info(f"Getting updates from last {hours}h")
        # Search with sort by last_edited_time
        results = self.client.search(
            page_size=15,
            sort={"timestamp": "last_edited_time", "direction": "descending"},
        ).get("results", [])

        # Filter by time
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        pages = self._parse_pages(results)
        pages = [p for p in pages if p.updated_at > cutoff]

        return NotionData(pages=pages, total_count=len(pages))

    def fetch_data(self, database_id: str | None = None) -> NotionData:
        """Fetch all pages or from specific database"""
        if database_id:
            logger.info(f"Fetching from database: {database_id}")
            results = self.client.databases.query(database_id=database_id).get(
                "results", []
            )
        else:
            logger.info("Fetching all pages")
            results = self.client.search(page_size=15).get("results", [])

        pages = self._parse_pages(results)
        return NotionData(pages=pages, total_count=len(pages))

    def get_page_content(self, page_id: str) -> str:
        """Get text content from a page"""
        logger.info(f"Fetching content: {page_id}")
        try:
            blocks = self.client.blocks.children.list(block_id=page_id)
            texts = []
            for block in blocks.get("results", []):
                block_type = block.get("type")
                data = block.get(block_type, {})
                if "rich_text" in data:
                    text = "".join(t.get("plain_text", "") for t in data["rich_text"])
                    if text:
                        texts.append(text)
            return "\n".join(texts)
        except Exception as e:
            logger.error(f"Content fetch failed: {e}")
            return ""

    def _parse_pages(self, results: list) -> list[NotionPage]:
        """Convert API results into NotionPage objects"""
        pages = []
        for r in results:
            if r.get("object") not in ["page", "database"]:
                continue

            try:
                pages.append(
                    NotionPage(
                        page_id=r["id"],
                        title=self._get_title(r),
                        properties=r.get("properties", {}),
                        updated_at=datetime.fromisoformat(
                            r["last_edited_time"].replace("Z", "+00:00")
                        ),
                        created_at=datetime.fromisoformat(
                            r["created_time"].replace("Z", "+00:00")
                        ),
                        url=r.get("url"),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse page: {e}")
                continue

        return pages

    def _get_title(self, obj: dict) -> str:
        """Extract title from Page or Database"""
        if obj.get("object") == "database":
            title_list = obj.get("title", [])
            return (
                "".join(t.get("plain_text", "") for t in title_list)
                or "Untitled Database"
            )

        for prop in obj.get("properties", {}).values():
            if prop.get("type") == "title":
                return "".join(t.get("plain_text", "") for t in prop.get("title", []))

        return "Untitled Page"

    def health_check(self) -> bool:
        try:
            self.client.users.me()
            return True
        except Exception:
            return False


notion_service = NotionService()