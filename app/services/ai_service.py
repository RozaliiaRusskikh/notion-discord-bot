from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage

from app.models import NotionData, ActionType
from app.config import settings
from app.logger import setup_logger

logger = setup_logger(__name__)


class AIService:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=settings.gemini_api_key,
            temperature=0.7,
            version="v1",
        )
        logger.info("✅ AI service ready")

    def generate_response(
        self,
        action: ActionType,
        data: NotionData,
        query: str | None = None,
    ) -> str:
        """Generate response based on action type"""

        prompts = {
            ActionType.STATUS: (
                "Provide a brief status report. Include total pages and recent activity.",
                self._format_pages(data),
            ),
            ActionType.SEARCH: (
                "Present these search results clearly.",
                (
                    f"Query: '{query}'\n\n{self._format_pages(data)}"
                    if data.pages
                    else f"No results for '{query}'"
                ),
            ),
            ActionType.LIST: (
                "List these pages in an organized format.",
                self._format_pages(data),
            ),
            ActionType.UPDATES: (
                "Summarize these recent changes. What was updated and when?",
                self._format_pages(data) if data.pages else "No recent updates.",
            ),
            ActionType.SUMMARY: (
                "Summarize this page. Key points and action items. Under 200 words.",
                (
                    f"Title: {data.pages[0].title}\n\n{data.pages[0].content}"
                    if data.pages
                    else "No page found."
                ),
            ),
        }

        system_msg, content = prompts.get(
            action, ("Summarize this data.", self._format_pages(data))
        )

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=system_msg),
                    HumanMessage(content=content),
                ]
            )
            return response.content
        except Exception as e:
            logger.error(f"AI error: {e}")
            return f"Error: {e}"

    def _format_pages(self, data: NotionData) -> str:
        """Format pages for AI context"""
        return "\n".join(
            f"- {p.title} (updated: {p.updated_at.strftime('%Y-%m-%d %H:%M')})"
            for p in data.pages
        )

    def health_check(self) -> bool:
        try:
            self.llm.invoke([HumanMessage(content="hi")])
            return True
        except Exception:
            return False


ai_service = AIService()
