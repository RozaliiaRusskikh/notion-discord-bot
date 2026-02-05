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


def _resolve_database_id(target: str) -> str | None:
    """Convert database name to ID, or return as-is if already an ID"""
    clean = target.replace("-", "")
    if len(clean) == 32 and all(c in "0123456789abcdef" for c in clean.lower()):
        return target

    logger.info(f"Looking up database: {target}")
    try:
        results = notion_service.client.search(
            query=target,
            filter={"property": "object", "value": "database"},
        ).get("results", [])

        if results:
            db_id = results[0]["id"]
            logger.info(f"Found database: {db_id}")
            return db_id

        logger.warning(f"Database not found: {target}")
        return None
    except Exception as e:
        logger.error(f"Database lookup failed: {e}")
        return None


def fetch(state: State) -> State:
    """Fetch data from Notion based on action"""
    cmd = state["command"]
    logger.info(f"Fetch: {cmd.action.value} → {cmd.target}")

    try:
        match cmd.action:
            # SEARCH: Just search, no ID needed
            case ActionType.SEARCH:
                data = notion_service.search_pages(cmd.query or cmd.target)

            # SUMMARY: Search for page by name → get ID → fetch content
            case ActionType.SUMMARY:
                data = notion_service.search_pages(cmd.target)
                if data.pages:
                    page_id = data.pages[0].page_id
                    data.pages[0].content = notion_service.get_page_content(page_id)

            # STATUS, LIST, UPDATES: Need database ID
            case ActionType.STATUS | ActionType.LIST | ActionType.UPDATES:
                database_id = _resolve_database_id(cmd.target)

                if not database_id:
                    data = NotionData(pages=[], total_count=0, database_id=None)
                elif cmd.action == ActionType.UPDATES:
                    data = notion_service.get_updates(database_id)
                else:
                    data = notion_service.query_database(database_id)

            # Fallback
            case _:
                data = notion_service.search_pages(cmd.target)

        return {**state, "data": data}

    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return {**state, "error": str(e)}


def analyze(state: State) -> State:
    """Generate AI response"""
    cmd = state["command"]
    data = state["data"]
    logger.info(f"Analyze: {cmd.action.value}")

    # Handle empty results
    if not data or not data.pages:
        messages = {
            ActionType.SEARCH: f"No results for '{cmd.query or cmd.target}'.",
            ActionType.SUMMARY: f"Page '{cmd.target}' not found.",
            ActionType.STATUS: f"Database '{cmd.target}' not found.",
            ActionType.LIST: f"Database '{cmd.target}' not found.",
            ActionType.UPDATES: f"No recent updates in '{cmd.target}'.",
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


def route(state: State) -> Literal["analyze", "error"]:
    """Route based on fetch result"""
    if state.get("error"):
        return "error"
    return "analyze"


# Build graph
graph = StateGraph(State)
graph.add_node("fetch", fetch)
graph.add_node("analyze", analyze)
graph.add_node("error", handle_error)

graph.set_entry_point("fetch")
graph.add_conditional_edges("fetch", route, {"analyze": "analyze", "error": "error"})
graph.add_edge("analyze", END)
graph.add_edge("error", END)

pipeline = graph.compile()
logger.info("✅ Pipeline ready")
