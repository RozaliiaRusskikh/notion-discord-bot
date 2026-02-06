from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END

from app.models import NotionData, Command, ActionType
from app.services.notion_service import notion_service
from app.services.ai_service import ai_service
from app.logger import setup_logger

logger = setup_logger(__name__)


class State(TypedDict):
    command: Command
    data: NotionData | None
    response: str | None
    error: str | None


def fetch(state: State) -> State:
    """Fetch data from Notion based on action"""
    cmd = state["command"]
    logger.info(f"Fetch: {cmd.action.value} → {cmd.target}")

    try:
        match cmd.action:
            case ActionType.SEARCH:
                # Search by keyword
                data = notion_service.search_by_keyword(cmd.query or cmd.target)

            case ActionType.LIST:
                # Get all pages
                data = notion_service.fetch_data()

            case ActionType.UPDATES:
                # Get recently edited pages
                data = notion_service.get_recent_updates()

            case ActionType.SUMMARY:
                # Search for page, then get its content
                data = notion_service.search_by_keyword(cmd.target)
                if data.pages:
                    page_id = data.pages[0].page_id
                    content = notion_service.get_page_content(page_id)
                    data.pages[0].content = content

            case _:
                data = notion_service.fetch_data()

        return {**state, "data": data}

    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return {**state, "error": str(e)}


def analyze(state: State) -> State:
    """Generate AI response"""
    cmd = state["command"]
    data = state["data"]
    logger.info(f"Analyze: {cmd.action.value}")

    if not data or not data.pages:
        messages = {
            ActionType.SEARCH: f"No results for '{cmd.query or cmd.target}'.",
            ActionType.SUMMARY: f"Page '{cmd.target}' not found.",
            ActionType.LIST: "No pages found in workspace.",
            ActionType.UPDATES: "No recent updates.",
        }
        return {**state, "response": messages.get(cmd.action, "No data found.")}

    try:
        response = ai_service.generate_response(
            action=cmd.action,
            data=data,
            query=cmd.query,
        )
        return {**state, "response": response}

    except Exception as e:
        logger.error(f"Analyze error: {e}")
        return {**state, "error": str(e)}


def handle_error(state: State) -> State:
    """Format error response"""
    return {**state, "response": f"❌ Error: {state.get('error', 'Unknown')}"}


def route(state: State) -> Literal["analyze", "handle_error"]:
    """Route based on fetch result"""
    if state.get("error"):
        return "handle_error"  # Changed from "error"
    return "analyze"


# Build graph
graph = StateGraph(State)
graph.add_node("fetch", fetch)
graph.add_node("analyze", analyze)
graph.add_node("handle_error", handle_error)

graph.set_entry_point("fetch")
graph.add_conditional_edges("fetch", route, {"analyze": "analyze", "handle_error": "handle_error"})
graph.add_edge("analyze", END)
graph.add_edge("handle_error", END)

pipeline = graph.compile()
logger.info("✅ Pipeline ready")