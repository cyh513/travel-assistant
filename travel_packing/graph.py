from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    checker_node,
    generator_node,
    parser_node,
    revisor_node,
    train_node,
    weather_node,
)
from .services import require_deepseek_api_key
from .state import TravelState


def _route_after_parser(state: TravelState) -> Literal["train", "weather", "generator", "revisor"]:
    if state.get("train_status") == "pending":
        return "train"
    if state.get("weather_refresh_needed"):
        return "weather"
    if state.get("is_update"):
        return "revisor"
    return "generator"


def _route_after_train(state: TravelState) -> Literal["weather", "generator", "revisor"]:
    if state.get("weather_refresh_needed"):
        return "weather"
    if state.get("is_update"):
        return "revisor"
    return "generator"


def _route_after_weather(state: TravelState) -> Literal["generator", "revisor"]:
    if state.get("weather_status") == "failed" or state.get("is_update"):
        return "revisor"
    return "generator"


def _route_after_revisor(state: TravelState) -> Literal["generator", "checker", "revisor"]:
    if state.get("weather_status") == "failed":
        return "revisor"
    if not state.get("packing_list") or not any(state["packing_list"].values()):
        return "generator"
    return "checker"


def _route_after_checker(state: TravelState) -> Literal["generator", "revisor", "end"]:
    if state.get("serious_issues"):
        return "revisor"
    if state.get("issues") and state.get("iteration", 0) < 3:
        return "generator"
    return "end"


def build_graph(checkpointer=None):
    require_deepseek_api_key()
    builder = StateGraph(TravelState)
    builder.add_node("parser", parser_node)
    builder.add_node("train", train_node)
    builder.add_node("weather", weather_node)
    builder.add_node("generator", generator_node)
    builder.add_node("checker", checker_node)
    builder.add_node("revisor", revisor_node)

    builder.add_edge(START, "parser")
    builder.add_conditional_edges("parser", _route_after_parser)
    builder.add_conditional_edges("train", _route_after_train)
    builder.add_conditional_edges("weather", _route_after_weather)
    builder.add_edge("generator", "checker")
    builder.add_conditional_edges(
        "checker",
        _route_after_checker,
        {"generator": "generator", "revisor": "revisor", "end": END},
    )
    builder.add_conditional_edges("revisor", _route_after_revisor)
    return builder.compile(checkpointer=checkpointer or MemorySaver())
