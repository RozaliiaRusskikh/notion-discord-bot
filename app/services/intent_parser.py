import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage

from app.models import Command, ActionType
from app.config import settings
from app.logger import setup_logger

logger = setup_logger(__name__)

SYSTEM_PROMPT = """You parse messages for a Notion Discord bot.

Actions:
- status: Database overview, health check
- search: Find pages by keyword
- list: Show all pages in database
- updates: Recent changes, what's new
- summary: Summarize specific page

Return JSON only:
{"action": "status|search|list|updates|summary", "target": "database or page name", "query": "search terms or null", "confidence": 0.0-1.0}

Examples:
"what's new in Projects?" → {"action": "updates", "target": "Projects", "query": null, "confidence": 0.9}
"find API docs" → {"action": "search", "target": "general", "query": "API docs", "confidence": 0.9}
"summarize meeting notes" → {"action": "summary", "target": "meeting notes", "query": null, "confidence": 0.85}
"show Projects database" → {"action": "list", "target": "Projects", "query": null, "confidence": 0.9}
"how's Tasks doing?" → {"action": "status", "target": "Tasks", "query": null, "confidence": 0.85}
"hello there" → {"action": "status", "target": "general", "query": null, "confidence": 0.1}
"""


class IntentParser:
    """Parse natural language into structured commands using Gemini"""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-pro",
            google_api_key=settings.gemini_api_key,
            temperature=0,
        )
        logger.info("✅ Intent parser ready")

    def parse(self, message: str, user_id: str) -> Command | None:
        """Parse message into Command or None if not Notion-related"""
        logger.info(f"Parsing: {message[:50]}...")

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=message),
                ]
            )

            result = json.loads(response.content.strip())
            logger.info(f"Intent: {result}")

            # Skip low confidence
            if result.get("confidence", 0) < 0.5:
                logger.info("Low confidence, ignoring")
                return None

            return Command(
                user_id=user_id,
                action=ActionType(result["action"]),
                target=result.get("target", "general"),
                query=result.get("query"),
                original_message=message,
            )

        except json.JSONDecodeError:
            logger.error("Failed to parse AI response as JSON")
            return None
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None


intent_parser = IntentParser()