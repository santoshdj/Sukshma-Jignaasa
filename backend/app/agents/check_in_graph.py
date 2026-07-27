"""
Check-In LangGraph StateGraph
------------------------------
Multi-turn conversational check-in with a human-in-the-loop confirmation gate.

Graph structure:
  START → ai_turn → route_after_ai
    "continue"  → human_turn  [interrupt_before — waits for patient message]
    "complete"  → confirm_gate [interrupt_before — waits for patient confirmation]

  human_turn (no-op): patient message is injected into state via update_state
  human_turn → ai_turn  (loops back)

  confirm_gate (no-op): patient confirm/edit is injected via update_state
  confirm_gate → END (on confirm) | ai_turn (on edit, to re-extract)

State persistence: MemorySaver (in-process RAM for POC).
Each session is identified by a UUID thread_id passed as configurable.thread_id.
"""

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.check_in_node import check_in_node
from app.models.check_in import CheckInState

logger = logging.getLogger(__name__)


# ── No-op gate nodes ──────────────────────────────────────────────────────────

def human_turn(state: CheckInState) -> dict:
    """
    No-op node. The graph interrupts BEFORE this node so the API can
    receive the patient's next message and inject it into state via update_state.
    After resume, this node executes (returning nothing) and the graph loops
    back to ai_turn.
    """
    return {}


def confirm_gate(state: CheckInState) -> dict:
    """
    No-op node. The graph interrupts BEFORE this node so the API can
    receive the patient's confirmation decision.
    On "confirm": state has human_confirmed=True → routes to END.
    On "edit": state has human_confirmed=False → routes back to ai_turn.
    """
    return {}


# ── Routing functions ─────────────────────────────────────────────────────────

def route_after_ai(state: CheckInState) -> str:
    """Route based on whether the AI has finished extracting."""
    if state.get("status") == "awaiting_confirmation":
        return "confirm_gate"
    if state.get("status") == "failed":
        return END
    return "human_turn"


def route_after_confirm(state: CheckInState) -> str:
    """Route based on patient decision at the confirmation gate."""
    if state.get("human_confirmed"):
        return END
    # Patient chose to edit — loop back to ai_turn with edit context
    return "ai_turn"


# ── Graph assembly ────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(CheckInState)

    builder.add_node("ai_turn", check_in_node)
    builder.add_node("human_turn", human_turn)
    builder.add_node("confirm_gate", confirm_gate)

    builder.set_entry_point("ai_turn")

    builder.add_conditional_edges(
        "ai_turn",
        route_after_ai,
        {
            "human_turn": "human_turn",
            "confirm_gate": "confirm_gate",
            END: END,
        },
    )

    # After human_turn no-op, loop back to ai_turn for next turn
    builder.add_edge("human_turn", "ai_turn")

    builder.add_conditional_edges(
        "confirm_gate",
        route_after_confirm,
        {
            "ai_turn": "ai_turn",
            END: END,
        },
    )

    return builder


# ── Compiled singleton ────────────────────────────────────────────────────────

_checkpointer = MemorySaver()

check_in_graph = _build_graph().compile(
    checkpointer=_checkpointer,
    interrupt_before=["human_turn", "confirm_gate"],
)

logger.info(
    "Check-in graph compiled with interrupt_before=['human_turn', 'confirm_gate']"
)
