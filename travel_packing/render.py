from __future__ import annotations

from .state import CATEGORIES, TravelState


CATEGORY_LABELS = {
    "clothing": "衣物",
    "electronics": "电子设备",
    "toiletries": "洗护",
    "documents": "证件/文件",
    "other": "其他",
}


def _format_train_lines(state: TravelState) -> list[str]:
    """Build console-friendly lines describing the 12306 train query results."""
    status = state.get("train_status", "skipped")
    if status == "skipped":
        return []
    origin = state.get("origin") or "未知"
    destination = state.get("destination") or "未知"
    train_date = state.get("start_date") or "待定"
    lines = ["", "[车次查询]"]
    lines.append(f"出发地：{origin} → 目的地：{destination}")
    lines.append(f"出发日期：{train_date}")
    if status == "failed":
        lines.append("状态：未能从 12306 获取车次信息（可能为网络问题或反爬限制）")
        return lines
    trains = state.get("train_results") or []
    if not trains:
        lines.append("状态：未查询到车次")
        return lines
    lines.append(f"共查询到 {len(trains)} 趟车次")
    lines.append("")
    for train in trains:
        seat_parts = []
        for label, key in (
            ("商务座", "business_seat"),
            ("特等座", "special_seat"),
            ("一等座", "first_seat"),
            ("二等座", "second_seat"),
            ("软卧", "soft_sleeper"),
            ("硬卧", "hard_sleeper"),
            ("硬座", "hard_seat"),
            ("无座", "no_seat"),
        ):
            value = train.get(key)
            if value and value != "无":
                seat_parts.append(f"{label}:{value}")
        seat_text = " ".join(seat_parts) if seat_parts else "无余票"
        can_buy = "可购票" if train.get("can_buy") == "Y" else "不可购"
        lines.append(
            f"- {train.get('train_number', '')}："
            f"{train.get('from_station', '')} {train.get('departure_time', '')} → "
            f"{train.get('to_station', '')} {train.get('arrival_time', '')} "
            f"（历时 {train.get('duration', '')}）| {can_buy} | {seat_text}"
        )
    return lines


def render_markdown(state: TravelState) -> str:
    title = "更新后" if state.get("is_update") else "初版"
    lines = [f"# 打包清单（{title}）", ""]
    origin = state.get("origin")
    if origin:
        lines.append(
            f"行程：{origin} → {state.get('destination') or '未识别目的地'} | "
            f"{state.get('start_date') or '日期待定'} 至 {state.get('end_date') or '日期待定'} | "
            f"{state.get('duration_days', 1)} 天"
        )
    else:
        lines.append(
            f"行程：{state.get('destination') or '未识别目的地'} | "
            f"{state.get('start_date') or '日期待定'} 至 {state.get('end_date') or '日期待定'} | "
            f"{state.get('duration_days', 1)} 天"
        )
    companion_text = "、".join(state.get("companions", []))
    travelers_line = f"出行人数：{state.get('travelers_count', 1)} 人"
    if companion_text:
        travelers_line += f"（同行：{companion_text}）"
    lines.append(travelers_line)

    if state.get("train_status") in ("ok", "failed"):
        trains = state.get("train_results") or []
        lines.extend(["", "## 车次查询"])
        lines.append(
            f"{state.get('origin')} → {state.get('destination')}  ·  "
            f"{state.get('start_date')}  ·  共 {len(trains)} 趟车次"
        )
        if state.get("train_status") == "failed":
            lines.append("未能从 12306 获取车次信息（可能为网络问题或反爬限制）。")
        elif trains:
            lines.extend(
                [
                    "",
                    "| 车次 | 出发站 | 到达站 | 出发 | 到达 | 历时 | 可购 | 一等座 | 二等座 | 硬座 | 无座 |",
                    "|---|---|---|---|---|---|---|---|---|---|---|",
                ]
            )
            for train in trains:
                lines.append(
                    f"| {train.get('train_number', '')} | "
                    f"{train.get('from_station', '')} | "
                    f"{train.get('to_station', '')} | "
                    f"{train.get('departure_time', '')} | "
                    f"{train.get('arrival_time', '')} | "
                    f"{train.get('duration', '')} | "
                    f"{'是' if train.get('can_buy') == 'Y' else '否'} | "
                    f"{train.get('first_seat', '--') or '--'} | "
                    f"{train.get('second_seat', '--') or '--'} | "
                    f"{train.get('hard_seat', '--') or '--'} | "
                    f"{train.get('no_seat', '--') or '--'} |"
                )

    weather = state.get("weather")
    if weather:
        if weather.get("temp_min_c") is not None and weather.get("temp_max_c") is not None:
            temperature = f"{weather['temp_min_c']}~{weather['temp_max_c']}°C"
        else:
            temperature = f"约 {weather.get('temp_c')}°C"
        location = (
            f"（定位：{weather.get('resolved_location')}）"
            if weather.get("resolved_location")
            else ""
        )
        source = f"，来源：{weather.get('source')}" if weather.get("source") else ""
        lines.append(
            f"天气{location}：{weather.get('condition')}，{temperature}，"
            f"降水概率 {weather.get('rain_prob')}%{source}"
        )
    lines.extend(["", "| 类别 | 物品 | 数量 | 原因 |", "|---|---|---:|---|"])
    packing = state.get("packing_list", {})
    for category in CATEGORIES:
        for item in packing.get(category, []):
            lines.append(
                f"| {CATEGORY_LABELS[category]} | {item['name']} | {item['quantity']} | {item['reason']} |"
            )

    if state.get("changes"):
        lines.extend(["", "## 本次修改"])
        lines.extend(f"- {change}" for change in state["changes"])
    if state.get("issues"):
        lines.extend(["", "## 仍需注意"])
        lines.extend(f"- {issue}" for issue in state["issues"])
    lines.extend(["", f"完整性置信度：{state.get('confidence', 0)}%"])
    return "\n".join(lines)


def render_console(state: TravelState) -> str:
    """Render a compact layout that remains readable in plain terminals."""
    title = "更新后" if state.get("is_update") else "初版"
    lines = [f"===== 打包清单（{title}）=====", ""]
    origin = state.get("origin")
    if origin:
        lines.append(f"出发地：{origin}")
    lines.append(f"目的地：{state.get('destination') or '未识别'}")
    lines.append(
        f"日期：{state.get('start_date') or '待定'} 至 "
        f"{state.get('end_date') or '待定'}（{state.get('duration_days', 1)} 天）"
    )
    companion_text = "、".join(state.get("companions", []))
    travelers = f"人数：{state.get('travelers_count', 1)} 人"
    if companion_text:
        travelers += f"，同行：{companion_text}"
    lines.append(travelers)

    train_lines = _format_train_lines(state)
    if train_lines:
        lines.extend(train_lines)

    weather = state.get("weather")
    if weather:
        lines.extend(["", "[真实天气查询]"])
        lines.append(f"预报日期：{state.get('start_date') or '待定'}")
        if weather.get("resolved_location"):
            lines.append(f"定位城市：{weather['resolved_location']}")
        if weather.get("temp_min_c") is not None and weather.get("temp_max_c") is not None:
            lines.append(f"温度范围：{weather['temp_min_c']}~{weather['temp_max_c']}°C")
        else:
            lines.append(f"参考温度：{weather.get('temp_c')}°C")
        lines.append(f"天气状况：{weather.get('condition')}")
        lines.append(f"最高降水概率：{weather.get('rain_prob')}%")
        if weather.get("precipitation_sum_mm") is not None:
            lines.append(f"预计全天降水量：{weather['precipitation_sum_mm']} mm")
        if weather.get("risk_note"):
            lines.append(f"风险说明：{weather['risk_note']}")
        lines.append(f"数据来源：{weather.get('source') or '用户提供'}")

    packing = state.get("packing_list", {})
    for category in CATEGORIES:
        items = packing.get(category, [])
        if not items:
            continue
        lines.extend(["", f"[{CATEGORY_LABELS[category]}]"])
        for item in items:
            lines.append(f"- {item['name']} x{item['quantity']}：{item['reason']}")

    if state.get("changes"):
        lines.extend(["", "[本次修改]"])
        lines.extend(f"- {change}" for change in state["changes"])
    if state.get("issues"):
        lines.extend(["", "[仍需注意]"])
        lines.extend(f"- {issue}" for issue in state["issues"])
    lines.extend(["", f"完整性置信度：{state.get('confidence', 0)}%"])
    return "\n".join(lines)
