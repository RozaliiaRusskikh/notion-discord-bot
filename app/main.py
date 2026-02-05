import discord
import asyncio
import httpx
from fastapi import FastAPI
from contextlib import asynccontextmanager
from datetime import datetime

from app.config import settings
from app.models import Command, HealthCheck, ActionType
from app.graph import pipeline, PipelineState
from app.command_parser import parser
from app.services.notion_service import notion_service
from app.services.ai_service import ai_service
from app.logger import setup_logger

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting bot...")
    asyncio.create_task(bot.start(settings.discord_token))
    yield
    logger.info("🛑 Shutting down...")
    await bot.close()


app = FastAPI(
    title="Notion Discord Bot",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Notion Discord Bot v1.0"}


@app.get("/health", response_model=HealthCheck)
async def health():
    return HealthCheck(
        status="healthy",
        discord=bot.is_ready(),
        notion=notion_service.health_check(),
        ai=ai_service.health_check(),
    )


@app.post("/process")
async def process_command(command: Command):
    logger.info(f"Processing: {command.action.value} {command.target}")

    initial_state: PipelineState = {
        "command": command,
        "notion_data": None,
        "response": None,
        "error": None,
        "pages_analyzed": 0,
    }

    result = pipeline.invoke(initial_state)

    return {
        "response": result.get("response", "Error"),
        "pages_analyzed": result.get("pages_analyzed", 0),
        "error": result.get("error"),
    }


intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    logger.info(f"✅ Bot connected: {bot.user}")
    logger.info(f"✅ Guilds: {len(bot.guilds)}")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    logger.info(f"📨 {message.author}: {message.content[:50]}...")

    cmd = parser.parse(message.content, str(message.author.id))
    if not cmd:
        return

    async with message.channel.typing():
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"http://{settings.api_host}:{settings.api_port}/process",
                    json=cmd.model_dump(mode="json"),
                    timeout=30.0,
                )
                result = response.json()

            colors = {
                ActionType.STATUS: discord.Color.blue(),
                ActionType.SEARCH: discord.Color.green(),
                ActionType.LIST: discord.Color.purple(),
                ActionType.UPDATES: discord.Color.orange(),
                ActionType.SUMMARY: discord.Color.gold(),
            }

            embed = discord.Embed(
                title=f"Notion {cmd.action.value.title()}: {cmd.target}",
                description=result["response"][:2000],
                color=colors.get(cmd.action, discord.Color.blue()),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"Pages: {result['pages_analyzed']}")

            await message.reply(embed=embed, mention_author=False)

        except Exception as e:
            logger.error(f"❌ Error: {e}")
            await message.reply(f"❌ Error: {str(e)[:200]}", mention_author=False)


if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 NOTION DISCORD BOT - STARTING")
    logger.info("Commands: status, search, list, updates, summary")
    logger.info(f"API Docs: http://{settings.api_host}:{settings.api_port}/docs")

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=int(settings.api_port),
        reload=False,
    )