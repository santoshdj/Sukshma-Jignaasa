"""
Hypothesis LangGraph StateGraph.

Flow:
  START → hypothesis_node → review_gate [interrupt_before]
  review_gate:
    "approve"     → END
    "regenerate"  → hypothesis_node (re-runs with feedback)
"""

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.hypothesis_node import hypothesis_node
from app.models.hypothesis import HypothesisState

logger = logging.getLogger(__name__)


def review_gate(state: HypothesisState) -> dict:
    """No-op. Graph interrupts BEFORE this node for patient review."""
    return {}


def route_after_review(state: HypothesisState) -> str:
    if state.get("human_approved"):
        return END
    if state.get("status") == "regenerate":
        return "hypothesis_node"
    return END


def _build_graph() -> StateGraph:
    builder = StateGraph(HypothesisState)
    builder.add_node("hypothesis_node", hypothesis_node)
    builder.add_node("review_gate", review_gate)
    builder.set_entry_point("hypothesis_node")
    builder.add_edge("hypothesis_node", "review_gate")
    builder.add_conditional_edges(
        "review_gate",
        route_after_review,
        {"hypothesis_node": "hypothesis_node", END: END},
    )
    return builder


_checkpointer = MemorySaver()
hypothesis_graph = _build_graph().compile(
    checkpointer=_checkpointer,
    interrupt_before=["review_gate"],
)
logger.info("Hypothesis graph compiled with interrupt_before=['review_gate']")
