from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


Category = Literal["clothing", "electronics", "toiletries", "documents", "other"]


class PackingItem(TypedDict):
    name: str
    quantity: int
    reason: str


class TravelState(TypedDict, total=False):
    # User input and parsed trip information.
    raw_input: str
    origin: str | None
    destination: str | None
    start_date: str | None
    end_date: str | None
    duration_days: int
    travelers_count: int
    companions: list[str]
    activities: list[str]
    special_events: list[str]
    constraints: list[str]

    # Train query results.
    train_results: list[dict[str, Any]]
    train_status: Literal["pending", "ok", "failed", "skipped"]

    # Weather and packing results.
    weather: dict[str, Any] | None
    weather_status: Literal["pending", "ok", "failed"]
    packing_list: dict[Category, list[PackingItem]]
    issues: list[str]
    serious_issues: list[str]
    changes: list[str]

    # Graph control fields.
    is_update: bool
    weather_refresh_needed: bool
    iteration: int
    is_complete: bool
    confidence: int
    pending_update: NotRequired[dict[str, Any]]


CATEGORIES: tuple[Category, ...] = (
    "clothing",
    "electronics",
    "toiletries",
    "documents",
    "other",
)


def empty_packing_list() -> dict[Category, list[PackingItem]]:
    return {category: [] for category in CATEGORIES}


def initial_state(raw_input: str) -> TravelState:
    return {
        "raw_input": raw_input,
        "origin": None,
        "destination": None,
        "start_date": None,
        "end_date": None,
        "duration_days": 1,
        "travelers_count": 1,
        "companions": [],
        "activities": [],
        "special_events": [],
        "constraints": [],
        "train_results": [],
        "train_status": "pending",
        "weather": None,
        "weather_status": "pending",
        "packing_list": empty_packing_list(),
        "issues": [],
        "serious_issues": [],
        "changes": [],
        "is_update": False,
        "weather_refresh_needed": True,
        "iteration": 0,
        "is_complete": False,
        "confidence": 0,
        "pending_update": {},
    }
