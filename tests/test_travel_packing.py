from __future__ import annotations

from langgraph.types import Command
import pytest

from travel_packing.graph import build_graph
from travel_packing.services import get_mock_weather
from travel_packing.state import initial_state


@pytest.fixture(autouse=True)
def deterministic_weather(monkeypatch):
    monkeypatch.setattr("travel_packing.nodes.get_weather", get_mock_weather)


def _names(state):
    return {
        item["name"]
        for items in state["packing_list"].values()
        for item in items
    }


def test_initial_trip_and_incremental_update():
    graph = build_graph()
    config = {"configurable": {"thread_id": "shanghai-demo"}}
    state = graph.invoke(
        initial_state("这周五去上海，待3天，参加行业展会，晚上有同行聚餐。"),
        config=config,
    )
    assert state["is_complete"] is True
    assert "折叠伞" in _names(state)
    original_names = _names(state)

    updated = graph.invoke(
        {"raw_input": "展会第二天我要做演讲，需要正装和笔记本电脑。", "is_update": True},
        config=config,
    )
    assert updated["is_complete"] is True
    assert original_names <= _names(updated)
    assert {"正装西装", "正式皮鞋", "笔记本电脑", "翻页笔", "U盘"} <= _names(updated)
    casual = next(item for item in updated["packing_list"]["clothing"] if item["name"] == "商务休闲装")
    assert casual["quantity"] == 2
    assert any("新增" in change for change in updated["changes"])


def test_weather_failure_interrupt_and_resume():
    graph = build_graph()
    config = {"configurable": {"thread_id": "unknown-city"}}
    state = graph.invoke(initial_state("明天去火星基地，待2天，开会。"), config=config)
    assert state["__interrupt__"]

    resumed = graph.invoke(Command(resume="8度，有雨，降水概率70%"), config=config)
    assert resumed["weather_status"] == "ok"
    assert resumed["is_complete"] is True
    assert "折叠伞" in _names(resumed)


def test_serious_cold_conflict_interrupt():
    graph = build_graph()
    config = {"configurable": {"thread_id": "cold-conflict"}}
    state = graph.invoke(
        initial_state("2027年1月11日去哈尔滨，待4天，参加会议，但我不想带厚外套。"),
        config=config,
    )
    assert state["__interrupt__"]

    resumed = graph.invoke(Command(resume="允许添加厚羽绒服"), config=config)
    assert resumed["is_complete"] is True
    assert "厚羽绒服" in _names(resumed)


def test_companion_update_recalculates_personal_items():
    graph = build_graph()
    config = {"configurable": {"thread_id": "companion-update"}}
    graph.invoke(
        initial_state("这周五去上海，待3天，参加行业展会。"),
        config=config,
    )
    updated = graph.invoke(
        {"raw_input": "可能有个女助理跟着我一起去，帮我重新统计所需要带的东西", "is_update": True},
        config=config,
    )

    assert updated["travelers_count"] == 2
    assert updated["companions"] == ["女助理"]
    clothing = {item["name"]: item for item in updated["packing_list"]["clothing"]}
    electronics = {item["name"]: item for item in updated["packing_list"]["electronics"]}
    documents = {item["name"]: item for item in updated["packing_list"]["documents"]}
    assert clothing["商务休闲装"]["quantity"] == 6
    assert clothing["内衣"]["quantity"] == 6
    assert clothing["舒适鞋"]["quantity"] == 2
    assert electronics["手机充电器"]["quantity"] == 2
    assert documents["身份证件"]["quantity"] == 2
    assert any("同行人数 1 -> 2" in change for change in updated["changes"])


def test_ordinal_activity_day_does_not_replace_trip_dates():
    graph = build_graph()
    config = {"configurable": {"thread_id": "ordinal-day-update"}}
    original = graph.invoke(
        initial_state("后天去上海，待2天，拜访客户。"),
        config=config,
    )
    updated = graph.invoke(
        {"raw_input": "第二天我要做演讲，还有一位女助理同行。", "is_update": True},
        config=config,
    )
    assert updated["start_date"] == original["start_date"]
    assert updated["end_date"] == original["end_date"]
