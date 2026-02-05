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
    """Safely converts database name to ID with exact-match priority"""
    clean = target.replace("-", "")
    if len(clean) == 32 and all(c in "0123456789abcdef" for c in clean.lower()):
        return target

    try:
        results = notion_service.client.search(
            query=target,
            filter={"property": "object", "value": "database"},
        ).get("results", [])

        if not results:
            return None

        # Try to find exact match first
        for res in results:
            title = notion_service._get_title(res)
            if title.lower() == target.lower():
                return res["id"]

        # Fallback to first search result
        return results[0]["id"]
    except Exception as e:
        logger.error(f"Database lookup failed: {e}")
        return None


def fetch(state: State) -> dict:
    cmd = state["command"]
    try:
        match cmd.action:
            case ActionType.SEARCH:
                data = notion_service.search_pages(cmd.query or cmd.target)

            case ActionType.SUMMARY:
                data = notion_service.search_pages(cmd.target)
                if data.pages:
                    # Enrich first page with full content
                    page_id = data.pages[0].page_id
                    data.pages[0].content = notion_service.get_page_content(page_id)

            case ActionType.STATUS | ActionType.LIST | ActionType.UPDATES:
                db_id = _resolve_database_id(cmd.target)
                if not db_id:
                    data = NotionData(pages=[], total_count=0)
                elif cmd.action == ActionType.UPDATES:
                    data = notion_service.get_updates(db_id)
                else:
                    data = notion_service.query_database(db_id)
            case _:
                data = notion_service.search_pages(cmd.target)

        return {"data": data, "error": None}
    except Exception as e:
        return {"error": str(e)}


def analyze(state: State) -> dict:
    cmd, data = state["command"], state["data"]

    if not data or not data.pages:
        # Custom logic for "No Results"
        msgs = {
            ActionType.UPDATES: "No recent updates found.",
            ActionType.SUMMARY: "Page not found.",
        }
        return {
            "response": msgs.get(
                cmd.action, f"Could not find any data for '{cmd.target}'."
            )
        }

    try:
        response = ai_service.generate_response(
            action=cmd.action, data=data, query=cmd.query
        )
        return {"response": response}
    except Exception as e:
        return {"error": str(e)}


def handle_error(state: State) -> dict:
    return {"response": f"❌ Error: {state.get('error', 'Unknown error occurred.')}"}


def route(state: State) -> Literal["analyze", "error"]:
    return "error" if state.get("error") else "analyze"


# Build Graph
workflow = StateGraph(State)
workflow.add_node("fetch", fetch)
workflow.add_node("analyze", analyze)
workflow.add_node("error", handle_error)

workflow.set_entry_point("fetch")
workflow.add_conditional_edges("fetch", route)
workflow.add_edge("analyze", END)
workflow.add_edge("error", END)

pipeline = workflow.compile()