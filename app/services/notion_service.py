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

    def create_standup_entry(
        self, database_id: str, date: datetime, commits: list[dict]
    ) -> tuple[str | None, str | None]:
        """
        Create a standup entry in Notion database based on GitHub commits
        
        Args:
            database_id: Notion database ID for standup notes
            date: Date for the standup entry
            commits: List of commit dictionaries from GitHub
            
        Returns:
            Tuple of (page_id, page_url) or (None, None) if failed
        """
        try:
            # Create commit summary
            commit_summary = self._format_commits_for_standup(commits)
            
            # Create page properties
            properties = {
                "title": {
                    "title": [{"text": {"content": "Standup"}}]
                }
            }
            
            # Log the database ID being used (for debugging)
            logger.info(f"Creating page in database: {database_id}")
            
            # Create the page
            page = self.client.pages.create(
                parent={"database_id": database_id},
                properties=properties,
            )
            
            page_id = page.get("id")
            page_url = page.get("url", "")
            
            # Add commit content as blocks
            if commit_summary:
                blocks = self._build_commit_blocks(commit_summary)
                self.client.blocks.children.append(block_id=page_id, children=blocks)
            
            logger.info(f"Created standup entry: {page_id}")
            return page_id, page_url
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            logger.error(f"Failed to create standup entry: {error_type}: {error_msg}")
            logger.error(f"Database ID used: {database_id}")
            
            # Provide helpful error messages based on error type
            if "Could not find database" in error_msg or "database_id" in error_msg.lower() or "object_not_found" in error_msg.lower():
                logger.error("⚠️ DATABASE ACCESS ISSUE:")
                logger.error("   1. Verify database_id in .env: database_id=2fe921b882a480909a08000cf440e9bd")
                logger.error("   2. Open your Notion database → Click '...' → 'Add connections'")
                logger.error("   3. Find and add your Notion integration (the one with your notion_api_key)")
                logger.error("   4. Ensure the integration has 'Edit' or 'Full access' permissions")
            elif "unauthorized" in error_msg.lower() or "permission" in error_msg.lower():
                logger.error("⚠️ PERMISSION ISSUE:")
                logger.error("   The integration doesn't have permission to create pages in this database")
                logger.error("   Go to database → Share → Check integration permissions")
            elif "validation_error" in error_msg.lower() or "invalid" in error_msg.lower():
                logger.error("⚠️ VALIDATION ISSUE:")
                logger.error("   Check if the database has a 'title' property (required for page creation)")
            else:
                logger.error("⚠️ UNKNOWN ERROR - Full details:")
                logger.error(f"   Error type: {error_type}")
                logger.error(f"   Error message: {error_msg}")
            
            return None, None

    def _create_bullet_block(self, text: str) -> dict:
        """Create a bulleted list item block"""
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            },
        }

    def _create_heading_block(self, text: str, level: int = 3) -> dict:
        """Create a heading block (level 2 or 3)"""
        heading_type = f"heading_{level}"
        return {
            "object": "block",
            "type": heading_type,
            heading_type: {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            },
        }

    def _build_commit_blocks(self, commit_summary: str) -> list[dict]:
        """Build Notion blocks from commit summary text"""
        blocks = [self._create_heading_block("Recent work", level=2)]
        
        lines = [line.strip() for line in commit_summary.split("\n") if line.strip()]
        current_commits = []
        
        for line in lines:
            if line.startswith("• "):
                # Commit message
                current_commits.append(line[2:])
            else:
                # Repo name - save previous commits and add repo heading
                if current_commits:
                    blocks.extend([self._create_bullet_block(msg) for msg in current_commits])
                    current_commits = []
                blocks.append(self._create_heading_block(line, level=3))
        
        # Add any remaining commits
        if current_commits:
            blocks.extend([self._create_bullet_block(msg) for msg in current_commits])
        
        return blocks

    def _format_commits_for_standup(self, commits: list[dict]) -> str:
        """Format commits grouped by repository"""
        if not commits:
            return "No commits since last standup."
        
        # Group commits by repository
        commits_by_repo = {}
        for commit in commits:
            repo = commit.get("repo", "")
            # Extract just the repo name (without owner)
            if "/" in repo:
                repo_name = repo.split("/")[-1]
            else:
                repo_name = repo if repo else "Unknown"
            
            # Format repo name to human-readable (e.g., "notion-discord-bot" → "Notion discord bot")
            repo_name_formatted = repo_name.replace("-", " ").replace("_", " ").title()
            
            if repo_name_formatted not in commits_by_repo:
                commits_by_repo[repo_name_formatted] = []
            
            message = commit.get("message", "").split("\n")[0]  # First line only
            commits_by_repo[repo_name_formatted].append(message)
        
        # Format: repo name as heading, then bullet list of commit messages
        lines = []
        for repo_name, repo_commits in commits_by_repo.items():
            lines.append(f"\n{repo_name}")
            for message in repo_commits:
                lines.append(f"• {message}")
        
        return "\n".join(lines).strip()

    def get_latest_standup_date(self, database_id: str) -> datetime | None:
        """
        Get the date of the most recent standup entry
        
        Args:
            database_id: Notion database ID for standup notes
            
        Returns:
            Datetime of latest standup or None if no standups found
        """
        try:
            # Query database using the Notion API
            # Note: This will fail if the database is not shared with the integration
            response = self.client.databases.query(
                database_id=database_id,
                sorts=[{"property": "created_time", "direction": "descending"}],
                page_size=1,
            )
            results = response.get("results", [])
            
            if not results:
                return None
            
            latest = results[0]
            created_time = latest.get("created_time", "")
            if created_time:
                return datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get latest standup date: {e}")
            return None

    def list_all_databases(self) -> list[dict]:
        """
        List all databases accessible to the integration
        
        Returns:
            List of dictionaries with database info (id, title, url)
        """
        try:
            results = self.client.search(
                filter={"property": "object", "value": "database"},
                page_size=100
            ).get("results", [])
            
            databases = []
            for result in results:
                if result.get("object") == "database":
                    databases.append({
                        "id": result.get("id"),
                        "title": self._get_title(result),
                        "url": result.get("url"),
                    })
            
            return databases
        except Exception as e:
            logger.error(f"Failed to list databases: {e}")
            # Fallback: try without filter
            try:
                all_results = self.client.search(page_size=100).get("results", [])
                databases = []
                for result in all_results:
                    if result.get("object") == "database":
                        databases.append({
                            "id": result.get("id"),
                            "title": self._get_title(result),
                            "url": result.get("url"),
                        })
                return databases
            except Exception as e2:
                logger.error(f"Fallback database listing also failed: {e2}")
                return []

    def health_check(self) -> bool:
        try:
            self.client.users.me()
            return True
        except Exception:
            return False


notion_service = NotionService()