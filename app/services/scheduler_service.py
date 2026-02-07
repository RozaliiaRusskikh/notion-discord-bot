from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone, timedelta
import discord
from app.config import settings
from app.services.github_service import github_service
from app.services.notion_service import notion_service
from app.logger import setup_logger

logger = setup_logger(__name__)


class SchedulerService:
    """Service to handle scheduled tasks for standup entries"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.pst = ZoneInfo("America/Los_Angeles")
        logger.info("✅ Scheduler service ready")

    def setup_standup_job(self):
        """Schedule standup job for Mon/Wed/Fri at 10:00am PST"""
        # Schedule for Monday, Wednesday, Friday at 10:00 AM PST
        trigger = CronTrigger(
            day_of_week="mon,wed,fri",
            hour=10,
            minute=0,
            timezone=self.pst,
        )

        self.scheduler.add_job(
            self.create_standup_entry,
            trigger=trigger,
            id="standup_entry",
            name="Create Standup Entry",
            replace_existing=True,
        )

        logger.info("✅ Standup job scheduled: Mon/Wed/Fri at 10:00 AM PST")

    def _format_commit_line(self, commit: dict, index: int) -> str:
        """Format a single commit as a line for Discord embed"""
        message = commit.get("message", "").split("\n")[0]
        if len(message) > 100:
            message = message[:97] + "..."

        author = commit.get("author", "Unknown")
        sha = commit.get("sha", "")
        url = commit.get("url", "")
        repo = commit.get("repo", "")

        if url:
            return f"{index}. [{sha[:7]}]({url}) {message} - *{author}*"
        return f"{index}. {sha[:7]} {message} - *{author}*"

    def _add_notion_link(
        self, embed: discord.Embed, page_id: str | None, page_url: str | None
    ):
        """Add Notion link field to embed"""
        if page_id and page_url:
            embed.add_field(
                name="📝 Notion document",
                value=f"[View in Notion]({page_url})",
                inline=False,
            )
        elif page_id:
            page_id_clean = page_id.replace("-", "")
            notion_url = f"https://www.notion.so/{page_id_clean}"
            embed.add_field(
                name="📝 Notion Entry",
                value=f"[View in Notion]({notion_url})",
                inline=False,
            )

    async def _get_discord_channel(self):
        """Get Discord channel, waiting for bot to be ready"""
        from app.main import bot
        import asyncio

        # Wait up to 30 seconds for bot to be ready
        max_wait = 30
        waited = 0

        while not bot.is_ready() and waited < max_wait:
            await asyncio.sleep(0.5)
            waited += 0.5

        if not bot.is_ready():
            logger.warning(f"Bot not ready after {max_wait}s - check DISCORD_TOKEN")
            return None

        channel = bot.get_channel(settings.standup_channel_id)
        if not channel:
            logger.error(
                f"Channel {settings.standup_channel_id} not found - check channel ID and bot permissions"
            )

        return channel

    async def send_standup_notification(
        self,
        commits: list[dict],
        page_id: str | None = None,
        page_url: str | None = None,
    ):
        """Send standup notification to Discord channel"""
        try:
            channel = await self._get_discord_channel()
            if not channel:
                return

            today = datetime.now(self.pst)
            date_str = today.strftime("%A, %B %d, %Y")

            # Create embed
            embed = discord.Embed(
                title=f"📋 Standup notes - {date_str}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc),
            )

            # Add commit information - show only 3 latest commits
            if commits:
                # Limit to 3 latest commits for display
                latest_commits = commits[:3]
                commit_lines = [
                    self._format_commit_line(commit, i + 1)
                    for i, commit in enumerate(latest_commits)
                ]
                
                commit_text = f"Found **{len(commits)}** commit(s)"
                if len(commits) > 3:
                    commit_text += f" (showing 3 latest - see Notion for all):\n\n"
                else:
                    commit_text += ":\n\n"
                
                commit_text += "\n".join(commit_lines)
                
                embed.add_field(
                    name="🔄 Recent Commits", value=commit_text, inline=False
                )
            else:
                embed.add_field(
                    name="🔄 Recent Commits",
                    value="No commits since last standup.",
                    inline=False,
                )

            # Add Notion link
            if page_id or page_url:
                self._add_notion_link(embed, page_id, page_url)
            elif not commits:
                embed.add_field(
                    name="⚠️ Notion document",
                    value="Failed to create Notion entry. Check server logs for details.",
                    inline=False,
                )
                embed.color = discord.Color.orange()

            embed.set_footer(text="Automated Standup Report")
            await channel.send(embed=embed)
            logger.info(
                f"✅ Sent standup notification to Discord channel {settings.standup_channel_id}"
            )

        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}", exc_info=True)

    async def create_standup_entry(self):
        """Create a standup entry in Notion based on recent GitHub commits"""
        try:
            logger.info("🔄 Running scheduled standup entry creation...")

            database_id = settings.database_id
            if not database_id:
                logger.error("Standup database ID not configured")
                return

            # Format database ID: remove dashes if present, then add them back in correct format
            # Notion expects format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            if database_id:
                # Remove any existing dashes
                clean_id = database_id.replace("-", "")
                # Add dashes in correct positions (8-4-4-4-12)
                if len(clean_id) == 32:
                    database_id = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"

            # Determine date range based on day of week
            today = datetime.now(self.pst)
            day_of_week = (
                today.weekday()
            )  # 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday

            # Calculate start date based on day:
            # Monday: fetch from Friday (previous week) and Monday (today)
            # Wednesday: fetch from Tuesday and Wednesday
            # Friday: fetch from Thursday and Friday
            if day_of_week == 0:  # Monday
                # Get commits from Friday (previous week) and Monday (today)
                # Start from Friday at 00:00:00 (3 days back)
                start_date = (today - timedelta(days=3)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                logger.info(
                    f"Monday standup: fetching commits from Friday ({start_date.date()}) and Monday ({today.date()})"
                )
            elif day_of_week == 2:  # Wednesday
                # Get commits from Tuesday and Wednesday
                # Start from Tuesday at 00:00:00 (1 day back)
                start_date = (today - timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                logger.info(
                    f"Wednesday standup: fetching commits from Tuesday ({start_date.date()}) and Wednesday ({today.date()})"
                )
            elif day_of_week == 4:  # Friday
                # Get commits from Thursday and Friday
                # Start from Thursday at 00:00:00 (1 day back)
                start_date = (today - timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                logger.info(
                    f"Friday standup: fetching commits from Thursday ({start_date.date()}) and Friday ({today.date()})"
                )
            else:
                # Fallback: use previous day
                start_date = (today - timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                logger.info(
                    f"Fallback: fetching commits from previous day ({start_date.date()}) to {today.date()}"
                )

            # Fetch commits since the calculated start date
            logger.info(f"Start date (PST): {start_date}, Today (PST): {today}")
            commits = github_service.get_commits_since_last_standup(start_date)
            logger.info(f"Found {len(commits)} commits since {start_date.date()}")
            if commits:
                logger.info(f"First commit date: {commits[0].get('date', 'N/A')}")
                logger.info(f"Last commit date: {commits[-1].get('date', 'N/A')}")

            # Log which repositories are being checked
            if github_service.repositories:
                repo_list = ", ".join(
                    [f"{r['owner']}/{r['repo']}" for r in github_service.repositories]
                )
                logger.info(f"Checking repositories: {repo_list}")
            else:
                logger.info("No repositories configured")

            # Create standup entry for today
            page_id, page_url = notion_service.create_standup_entry(
                database_id=database_id,
                date=today,
                commits=commits,
            )

            if page_id:
                logger.info(f"✅ Successfully created standup entry: {page_id}")
            else:
                logger.error(
                    "❌ Failed to create standup entry - check logs above for details"
                )
                logger.error("Common issues:")
                logger.error("  1. Database not shared with Notion integration")
                logger.error("  2. Incorrect database_id format")
                logger.error("  3. Integration lacks 'Insert' permissions")

            # Send Discord notification (even if Notion creation failed)
            await self.send_standup_notification(commits, page_id, page_url)

        except Exception as e:
            logger.error(f"Error creating standup entry: {e}", exc_info=True)

    def start(self):
        """Start the scheduler"""
        self.setup_standup_job()
        self.scheduler.start()
        logger.info("✅ Scheduler started")

    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
        logger.info("✅ Scheduler stopped")


scheduler_service = SchedulerService()
