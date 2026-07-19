from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import re
from typing import Any

from langgraph.types import interrupt

from .services import get_weather, parse_manual_weather, parse_trip_info, query_12306_trains
from .state import CATEGORIES, PackingItem, TravelState, empty_packing_list


def _merge_unique(current: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys(current + additions))


def _update_mentions_trip_date(text: str) -> bool:
    """Ordinal activity days such as '第二天' must not replace trip dates."""
    explicit_date = re.search(
        r"(?:改到|改成|延期到|提前到|出发改为|出发日期|行程改为).*?"
        r"(?:今天|明天|后天|下周|这周|本周|周[一二三四五六日天]|星期[一二三四五六日天]|"
        r"\d{1,4}[年/-]\d{1,2}[月/-]\d{1,2})",
        text,
    )
    return bool(explicit_date)


def parser_node(state: TravelState) -> dict[str, Any]:
    parsed = parse_trip_info(state["raw_input"])
    is_update = bool(state.get("is_update"))
    old_destination = state.get("destination")
    old_origin = state.get("origin")
    old_dates = (state.get("start_date"), state.get("end_date"))
    old_travelers = state.get("travelers_count", 1)
    old_train_status = state.get("train_status", "pending")

    if is_update:
        origin = parsed.get("origin") or old_origin
        destination = parsed.get("destination") or old_destination
        if _update_mentions_trip_date(state["raw_input"]):
            start_date = parsed.get("start_date") or state.get("start_date")
            end_date = parsed.get("end_date") or state.get("end_date")
            duration = parsed.get("duration_days") or state.get("duration_days", 1)
        else:
            start_date = state.get("start_date")
            end_date = state.get("end_date")
            duration = state.get("duration_days", 1)
        travelers = parsed.get("travelers_count") or old_travelers
        companions = _merge_unique(state.get("companions", []), parsed.get("companions", []))
        activities = _merge_unique(state.get("activities", []), parsed.get("activities", []))
        events = _merge_unique(state.get("special_events", []), parsed.get("special_events", []))
        constraints = _merge_unique(state.get("constraints", []), parsed.get("constraints", []))
    else:
        origin = parsed.get("origin")
        destination = parsed.get("destination")
        start_date = parsed.get("start_date")
        end_date = parsed.get("end_date")
        duration = parsed.get("duration_days") or 1
        travelers = parsed.get("travelers_count") or 1
        companions = parsed.get("companions", [])
        activities = parsed.get("activities", [])
        events = parsed.get("special_events", [])
        constraints = parsed.get("constraints", [])

    if start_date and duration and not end_date:
        end_date = (date.fromisoformat(start_date) + timedelta(days=duration - 1)).isoformat()

    weather_refresh = not is_update or destination != old_destination or (start_date, end_date) != old_dates

    # Train query is triggered when origin, destination, and start_date are all
    # known and either this is the first time or one of them has changed.
    train_refresh = (
        origin is not None
        and destination is not None
        and start_date is not None
        and (
            old_train_status != "ok"
            or origin != old_origin
            or destination != old_destination
            or (start_date, end_date) != old_dates
        )
    )
    if origin is None:
        train_status: str = "skipped"
    elif train_refresh:
        train_status = "pending"
    else:
        train_status = old_train_status if old_train_status in ("ok", "failed") else "skipped"

    return {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "duration_days": max(1, int(duration)),
        "travelers_count": max(1, int(travelers)),
        "companions": companions,
        "activities": activities,
        "special_events": events,
        "constraints": constraints,
        "train_results": [] if train_refresh else state.get("train_results", []),
        "train_status": train_status,
        "pending_update": (
            {**parsed, "_previous_travelers_count": old_travelers}
            if is_update
            else {}
        ),
        "weather_refresh_needed": weather_refresh,
        "weather_status": "pending" if weather_refresh else state.get("weather_status", "pending"),
        "issues": [],
        "serious_issues": [],
        "changes": [],
        "iteration": 0,
        "is_complete": False,
    }


def train_node(state: TravelState) -> dict[str, Any]:
    """Query 12306 for available trains when origin, destination, and date are provided."""
    origin = state.get("origin")
    destination = state.get("destination")
    train_date = state.get("start_date")
    if not origin or not destination or not train_date:
        return {"train_status": "skipped", "train_results": []}

    result = query_12306_trains(origin, destination, train_date)
    if result is None:
        return {
            "train_status": "failed",
            "train_results": [],
            "changes": [f"未能从 12306 查询到 {origin} → {destination}（{train_date}）的车次信息"],
        }
    trains = result.get("results", [])
    return {
        "train_status": "ok",
        "train_results": trains,
        "changes": [
            f"已查询 {origin} → {destination}（{train_date}）共 {len(trains)} 趟车次"
        ],
    }


def weather_node(state: TravelState) -> dict[str, Any]:
    weather = get_weather(state.get("destination"), state.get("start_date"))
    if weather is None:
        return {"weather": None, "weather_status": "failed", "is_complete": False}
    return {"weather": weather, "weather_status": "ok"}


def _item(name: str, quantity: int = 1, reason: str = "基础出行需要") -> PackingItem:
    return {"name": name, "quantity": max(1, quantity), "reason": reason}


def _find(items: list[PackingItem], name: str) -> PackingItem | None:
    return next((item for item in items if item["name"] == name), None)


def _upsert(
    packing: dict[str, list[PackingItem]],
    category: str,
    name: str,
    quantity: int = 1,
    reason: str = "",
    allow_decrease: bool = False,
) -> str | None:
    existing = _find(packing[category], name)
    if existing:
        if quantity > existing["quantity"] or (allow_decrease and quantity != existing["quantity"]):
            old = existing["quantity"]
            existing["quantity"] = quantity
            if reason:
                existing["reason"] = reason
            return f"调整 {name}：{old} -> {quantity}"
        if allow_decrease and reason and reason != existing.get("reason"):
            existing["reason"] = reason
        return None
    packing[category].append(_item(name, quantity, reason or "行程需要"))
    return f"新增 {name} x{quantity}"


def _recommended_items(state: TravelState) -> dict[str, list[PackingItem]]:
    days = state.get("duration_days", 1)
    travelers = state.get("travelers_count", 1)
    activities = set(state.get("activities", []))
    events = set(state.get("special_events", []))
    weather = state.get("weather") or {}
    packing: dict[str, list[PackingItem]] = empty_packing_list()

    business = bool(activities & {"商务会议", "行业展会", "演讲"})
    formal = "演讲" in activities or bool(events & {"见重要客户", "正式场合"})
    casual_count = max(1, days - (1 if formal else 0))
    if business:
        packing["clothing"].append(
            _item("商务休闲装", casual_count * travelers, f"{travelers} 人商务活动日常穿着")
        )
        packing["documents"].append(_item("名片", 1, "商务交流"))
    else:
        packing["clothing"].append(_item("日常上衣", days * travelers, "按人数和行程天数准备"))

    packing["clothing"].extend(
        [
            _item("内衣", days * travelers, "按人数和行程天数准备"),
            _item("袜子", days * travelers, "按人数和行程天数准备"),
            _item("舒适鞋", travelers, "每人一双，用于通勤与步行"),
        ]
    )
    packing["electronics"].extend(
        [
            _item("手机充电器", travelers, "每人一个必备电子配件"),
            _item("充电宝", 1, "移动补电"),
        ]
    )
    packing["toiletries"].extend(
        [
            _item("旅行装牙刷牙膏", travelers, "每人一套基础洗护"),
            _item("常用药", 1, "应急用品"),
        ]
    )
    packing["documents"].append(_item("身份证件", travelers, "每人携带，用于交通与入住"))

    if formal:
        packing["clothing"].extend(
            [
                _item("正装西装", 1, "演讲或重要客户场合"),
                _item("正式皮鞋", 1, "与正装搭配"),
            ]
        )
    if "演讲" in activities:
        packing["electronics"].extend(
            [
                _item("笔记本电脑", 1, "演讲材料"),
                _item("笔记本电脑充电器", 1, "电脑供电"),
                _item("翻页笔", 1, "现场演讲"),
                _item("U盘", 1, "备份 PPT"),
            ]
        )
        packing["other"].append(_item("确认投影接口", 1, "提前确认 HDMI/VGA/Type-C"))
    elif "需要笔记本电脑" in events:
        packing["electronics"].extend(
            [
                _item("笔记本电脑", 1, "用户明确要求"),
                _item("笔记本电脑充电器", 1, "电脑供电"),
            ]
        )
    if "健身" in activities:
        packing["clothing"].extend(
            [
                _item("运动服", 1, "健身使用"),
                _item("运动鞋", 1, "健身使用"),
            ]
        )
    if "游泳" in activities:
        packing["clothing"].extend(
            [
                _item("泳衣", 1, "游泳使用"),
                _item("泳镜", 1, "游泳使用"),
            ]
        )
        packing["other"].append(_item("防水收纳袋", 1, "收纳湿泳具"))

    temp = weather.get("temp_c")
    if isinstance(temp, (int, float)):
        if temp < 0:
            if "不带厚外套" not in state.get("constraints", []):
                packing["clothing"].append(_item("厚羽绒服", 1, "零下天气保暖"))
        elif temp <= 10:
            packing["clothing"].append(_item("保暖外套", 1, "低温天气保暖"))
        elif temp <= 20:
            packing["clothing"].append(_item("薄外套", 1, "早晚温差"))
    if weather.get("needs_umbrella"):
        packing["other"].append(_item("折叠伞", travelers, "降水概率较高，建议每人一把"))
    if weather.get("needs_sunscreen"):
        packing["toiletries"].append(_item("防晒霜", 1, "高温或日晒"))
    if state.get("destination") in {"东京", "首尔", "新加坡", "伦敦", "巴黎", "纽约"}:
        packing["electronics"].append(_item("转换插头", 1, "境外用电标准可能不同"))
        packing["documents"].append(_item("护照", 1, "境外出行"))
    return packing


def generator_node(state: TravelState) -> dict[str, Any]:
    packing = _recommended_items(state)
    changes: list[str] = []

    # On retries, explicitly patch issues so the checker-generator loop converges.
    for issue in state.get("issues", []):
        if "袜子" in issue:
            quantity = state.get("duration_days", 1) * state.get("travelers_count", 1)
            change = _upsert(packing, "clothing", "袜子", quantity, "按人数和天数补足")
        elif "手机充电器" in issue:
            change = _upsert(packing, "electronics", "手机充电器", 1, "补齐必备配件")
        elif "电脑充电器" in issue:
            change = _upsert(packing, "electronics", "笔记本电脑充电器", 1, "电脑供电")
        elif "正式皮鞋" in issue:
            change = _upsert(packing, "clothing", "正式皮鞋", 1, "正式场合搭配")
        elif "厚外套" in issue and "不带厚外套" not in state.get("constraints", []):
            change = _upsert(packing, "clothing", "厚羽绒服", 1, "零下天气保暖")
        else:
            change = None
        if change:
            changes.append(change)
    return {
        "packing_list": packing,
        "iteration": state.get("iteration", 0) + 1,
        "changes": changes,
        "is_complete": False,
    }


def checker_node(state: TravelState) -> dict[str, Any]:
    packing = state.get("packing_list", empty_packing_list())
    names = {item["name"] for category in CATEGORIES for item in packing.get(category, [])}
    issues: list[str] = []
    serious: list[str] = []
    days = state.get("duration_days", 1)
    travelers = state.get("travelers_count", 1)
    activities = set(state.get("activities", []))
    events = set(state.get("special_events", []))

    socks = _find(packing.get("clothing", []), "袜子")
    expected_socks = days * travelers
    if days > 3 and (not socks or socks["quantity"] < expected_socks):
        issues.append(f"{travelers} 人行程 {days} 天，但袜子数量不足")
    if "手机充电器" not in names:
        issues.append("遗漏手机充电器")
    if "笔记本电脑" in names and "笔记本电脑充电器" not in names:
        issues.append("有笔记本电脑但遗漏电脑充电器")

    formal = "演讲" in activities or bool(events & {"见重要客户", "正式场合"})
    if formal and "正式皮鞋" not in names:
        issues.append("正式活动需要正式皮鞋，不能只依赖运动鞋或舒适鞋")

    temp = (state.get("weather") or {}).get("temp_c")
    warm_items = {"厚羽绒服", "保暖外套"} & names
    if isinstance(temp, (int, float)) and temp < 0 and not warm_items:
        message = f"目的地预计 {temp}°C，但清单没有可靠的御寒外套"
        issues.append(message)
        serious.append(message)

    complete = not issues
    confidence = 95 if complete and state.get("weather_status") == "ok" else 82 if complete else 55
    return {
        "issues": issues,
        "serious_issues": serious,
        "is_complete": complete,
        "confidence": confidence,
    }


def revisor_node(state: TravelState) -> dict[str, Any]:
    # Revisor doubles as the weather fallback and serious-issue HITL coordinator.
    if state.get("weather_status") == "failed":
        answer = interrupt(
            {
                "type": "weather_required",
                "message": (
                    f"无法获取 {state.get('destination') or '目的地'} 的天气。"
                    "请手动输入预计温度和降水情况，例如：8度，有雨，降水概率70%。"
                ),
            }
        )
        weather = parse_manual_weather(str(answer))
        if weather is None:
            return {
                "weather_status": "failed",
                "issues": ["手动天气信息中没有识别到温度，请再次补充"],
                "is_complete": False,
            }
        update: dict[str, Any] = {
            "weather": weather,
            "weather_status": "ok",
            "changes": ["采用用户提供的天气信息"],
        }
        if state.get("is_update") and any((state.get("packing_list") or {}).values()):
            packing = deepcopy(state["packing_list"])
            recommended = _recommended_items({**state, "weather": weather})
            changes = update["changes"]
            for category in CATEGORIES:
                packing.setdefault(category, [])
                for item in recommended[category]:
                    change = _upsert(
                        packing,
                        category,
                        item["name"],
                        item["quantity"],
                        item["reason"],
                        allow_decrease=True,
                    )
                    if change:
                        changes.append(change)
            update["packing_list"] = packing
        return update

    packing = deepcopy(state.get("packing_list") or empty_packing_list())
    for category in CATEGORIES:
        packing.setdefault(category, [])
    changes: list[str] = []
    pending = state.get("pending_update", {})
    previous_travelers = pending.get("_previous_travelers_count")
    if previous_travelers and previous_travelers != state.get("travelers_count"):
        companion_text = "、".join(state.get("companions", [])) or "同行者"
        changes.append(
            f"同行人数 {previous_travelers} -> {state.get('travelers_count')}（新增：{companion_text}）"
        )

    if state.get("serious_issues"):
        answer = interrupt(
            {
                "type": "serious_issue",
                "message": "发现需要你确认的严重问题："
                + "；".join(state["serious_issues"])
                + "。请说明如何处理，例如允许添加厚羽绒服。",
            }
        )
        extra = parse_trip_info(str(answer), use_llm=False)
        constraints = state.get("constraints", [])
        if any(token in str(answer) for token in ("允许", "添加", "带上", "羽绒服", "厚外套")):
            constraints = [item for item in constraints if item != "不带厚外套"]
            change = _upsert(packing, "clothing", "厚羽绒服", 1, "用户确认用于零下保暖")
            if change:
                changes.append(change)
        return {
            "packing_list": packing,
            "constraints": _merge_unique(constraints, extra.get("constraints", [])),
            "changes": changes or ["已记录用户对严重问题的回复"],
            "serious_issues": [],
            "issues": [],
        }

    recommended = _recommended_items(state)
    for category in CATEGORIES:
        for item in recommended[category]:
            change = _upsert(
                packing,
                category,
                item["name"],
                item["quantity"],
                item["reason"],
                allow_decrease=True,
            )
            if change:
                changes.append(change)
    return {
        "packing_list": packing,
        "changes": changes or ["新信息未要求修改现有清单"],
        "issues": [],
        "serious_issues": [],
        "is_complete": False,
    }
