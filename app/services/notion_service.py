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
        logger.info(f"Querying: {database_id}")
        results = self.client.databases.query(database_id=database_id)
        pages = self._parse_pages(results.get("results", [])[:15])
        return NotionData(pages=pages, total_count=len(pages), database_id=database_id)

    def search_pages(self, query: str) -> NotionData:
        logger.info(f"Searching: {query}")
        results = self.client.search(query=query, page_size=10).get("results", [])
        pages = self._parse_pages(results)
        return NotionData(pages=pages, total_count=len(pages))

    def get_updates(self, database_id: str, hours: int = 24) -> NotionData:
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
        pages = []
        for r in results:
            # Skip objects that aren't pages or databases
            if r.get("object") not in ["page", "database"]:
                continue

            updated_str = r["last_edited_time"].replace("Z", "+00:00")
            created_str = r["created_time"].replace("Z", "+00:00")

            pages.append(
                NotionPage(
                    page_id=r["id"],
                    title=self._get_title(r),
                    properties=r.get("properties", {}),
                    updated_at=datetime.fromisoformat(updated_str),
                    created_at=datetime.fromisoformat(created_str),
                    url=r.get("url"),
                )
            )
        return pages

    def _get_title(self, obj: dict) -> str:
        """Extract title from either a Page or a Database object"""
        # Databases have a top-level 'title' list
        if obj.get("object") == "database":
            title_list = obj.get("title", [])
            return (
                "".join(t.get("plain_text", "") for t in title_list)
                or "Untitled Database"
            )

        # Pages have title inside 'properties'
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