from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from app.models import NotionData, Command, ActionType
from app.services.notion_service import notion_service
from app.services.ai_service import ai_service
from app.logger import setup_logger

logger = setup_logger(__name__)


class PipelineState(TypedDict):
    command: Command
    notion_data: NotionData | None
    response: str | None
    error: str | None
    pages_analyzed: int


def fetch_data(state: PipelineState) -> PipelineState:
    cmd = state["command"]
    logger.info(f"Fetching: {cmd.action.value}")

    try:
        if cmd.action == ActionType.SEARCH:
            data = notion_service.search_pages(cmd.query or cmd.target)
        elif cmd.action == ActionType.UPDATES:
            data = notion_service.get_recent_updates(cmd.target)
        elif cmd.action == ActionType.SUMMARY:
            data = notion_service.search_pages(cmd.target)
            if data.pages:
                content = notion_service.get_page_content(data.pages[0].page_id)
                data.pages[0].content = content
        else:
            data = notion_service.query_database(cmd.target)

        return {
            **state,
            "notion_data": data,
            "pages_analyzed": len(data.pages),
        }
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        return {**state, "error": str(e)}


def analyze_data(state: PipelineState) -> PipelineState:
    cmd = state["command"]
    logger.info(f"Analyzing: {cmd.action.value}")

    try:
        response = ai_service.process_action(
            action=cmd.action,
            notion_data=state["notion_data"],
            query=cmd.query,
        )
        return {**state, "response": response}
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {**state, "error": str(e)}


def handle_error(state: PipelineState) -> PipelineState:
    error = state.get("error", "Unknown error")
    return {**state, "response": f"❌ Error: {error}"}


def route_after_fetch(state: PipelineState) -> Literal["analyze", "error"]:
    if state.get("error"):
        return "error"
    if state["pages_analyzed"] == 0 and state["command"].action != ActionType.UPDATES:
        return "error"
    return "analyze"


workflow = StateGraph(PipelineState)

workflow.add_node("fetch", fetch_data)
workflow.add_node("analyze", analyze_data)
workflow.add_node("error", handle_error)

workflow.set_entry_point("fetch")

workflow.add_conditional_edges(
    "fetch",
    route_after_fetch,
    {"analyze": "analyze", "error": "error"},
)

workflow.add_edge("analyze", END)
workflow.add_edge("error", END)

pipeline = workflow.compile()
logger.info("✅ LangGraph pipeline compiled")