import discord
from discord import app_commands
import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from datetime import datetime

from app.config import settings
from app.models import Command, HealthCheck, ActionType
from app.graph import pipeline, State
from app.services.intent_parser import intent_parser
from app.services.notion_service import notion_service
from app.services.ai_service import ai_service
from app.logger import setup_logger

logger = setup_logger(__name__, "bot.log")


# ===== HELPERS =====


async def process_command(cmd: Command) -> dict:
    """Run command through pipeline"""
    state: State = {
        "command": cmd,
        "data": None,
        "response": None,
        "error": None,
    }
    result = pipeline.invoke(state)
    return {
        "response": result.get("response", "Error"),
        "pages": len(result["data"].pages) if result.get("data") else 0,
        "error": result.get("error"),
    }


def create_embed(
    title: str, content: str, action: ActionType, pages: int
) -> discord.Embed:
    """Create Discord embed"""
    colors = {
        ActionType.SEARCH: discord.Color.blue(),
        ActionType.LIST: discord.Color.purple(),
        ActionType.UPDATES: discord.Color.green(),
        ActionType.SUMMARY: discord.Color.gold(),
    }
    embed = discord.Embed(
        title=title,
        description=content[:4000],
        color=colors.get(action, discord.Color.blue()),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=f"📄 {pages} pages analyzed")
    return embed


# ===== DISCORD BOT =====


class NotionBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("✅ Slash commands synced")


bot = NotionBot()


@bot.event
async def on_ready():
    logger.info(f"✅ Bot ready: {bot.user}")
    logger.info(f"✅ Servers: {len(bot.guilds)}")


# ===== SLASH COMMAND =====


@bot.tree.command(name="notion", description="Query your Notion workspace")
@app_commands.describe(
    action="What to do",
    query="Search terms or page name (optional)",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="📊 Status - Workspace overview", value="status"),
        app_commands.Choice(name="🔍 Search - Find by keyword", value="search"),
        app_commands.Choice(name="📋 List - All pages", value="list"),
        app_commands.Choice(name="🔄 Updates - Recent changes", value="updates"),
        app_commands.Choice(name="📝 Summary - Summarize a page", value="summary"),
    ]
)
async def slash_notion(
    interaction: discord.Interaction,
    action: str,
    query: str | None = None,
):
    await interaction.response.defer()

    cmd = Command(
        user_id=str(interaction.user.id),
        action=ActionType(action),
        target=query or "workspace",
        query=query,
    )

    result = await process_command(cmd)

    title = f"Notion {action.title()}"
    if query:
        title += f": {query}"

    embed = create_embed(
        title=title,
        content=result["response"],
        action=cmd.action,
        pages=result["pages"],
    )

    await interaction.followup.send(embed=embed)


# ===== NATURAL LANGUAGE =====


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.content.startswith("/"):
        return

    # Parse with AI
    cmd = intent_parser.parse(message.content, str(message.author.id))
    if not cmd:
        return

    logger.info(f"📨 {message.author}: {message.content[:50]}...")

    async with message.channel.typing():
        result = await process_command(cmd)

        title = f"Notion {cmd.action.value.title()}"
        if cmd.target and cmd.target != "workspace":
            title += f": {cmd.target}"

        embed = create_embed(
            title=title,
            content=result["response"],
            action=cmd.action,
            pages=result["pages"],
        )

        await message.reply(embed=embed, mention_author=False)


# ===== FASTAPI =====


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting...")
    asyncio.create_task(bot.start(settings.discord_token))
    yield
    await bot.close()


api = FastAPI(title="Notion Discord Bot", lifespan=lifespan)


@api.get("/")
async def root():
    return {"status": "ok", "message": "Notion Discord Bot"}


@api.get("/health", response_model=HealthCheck)
async def health():
    return HealthCheck(
        status="healthy",
        discord=bot.is_ready(),
        notion=notion_service.health_check(),
        ai=ai_service.health_check(),
    )


# ===== RUN =====

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 50)
    logger.info("🚀 NOTION DISCORD BOT")
    logger.info("=" * 50)
    logger.info("Slash commands:")
    logger.info("  /notion action:status")
    logger.info("  /notion action:search query:meeting")
    logger.info("  /notion action:list")
    logger.info("  /notion action:updates")
    logger.info("  /notion action:summary query:roadmap")
    logger.info("")
    logger.info("Natural language:")
    logger.info("  What's in my workspace?")
    logger.info("  Find docs about API")
    logger.info("  Show recent updates")
    logger.info("  Summarize the roadmap")
    logger.info("")
    logger.info(f"API: http://{settings.api_host}:{settings.api_port}/docs")
    logger.info("=" * 50)

    uvicorn.run(
        "app.main:api",
        host=settings.api_host,
        port=settings.api_port,
    )
