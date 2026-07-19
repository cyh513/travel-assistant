from __future__ import annotations

from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv
from langgraph.types import Command

from travel_packing.graph import build_graph
from travel_packing.state import CATEGORIES, TravelState, initial_state


load_dotenv()

st.set_page_config(
    page_title="旅行小助手",
    page_icon="🧳",
    layout="wide",
    initial_sidebar_state="expanded",
)

CATEGORY_META = {
    "clothing": ("👔", "衣物"),
    "electronics": ("🔌", "电子设备"),
    "toiletries": ("🧴", "洗护用品"),
    "documents": ("📄", "证件与文件"),
    "other": ("📦", "其他"),
}


def init_session() -> None:
    if "graph" not in st.session_state:
        st.session_state.graph = build_graph()
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid4())
    if "result" not in st.session_state:
        st.session_state.result = None
    if "pending_interrupt" not in st.session_state:
        st.session_state.pending_interrupt = None
    if "packed" not in st.session_state:
        st.session_state.packed = {}
    if "last_error" not in st.session_state:
        st.session_state.last_error = None


def config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def item_key(category: str, name: str) -> str:
    return f"{category}:{name}"


def capture_result(result: TravelState) -> None:
    st.session_state.result = result
    interrupts = result.get("__interrupt__")
    st.session_state.pending_interrupt = interrupts[0].value if interrupts else None


def invoke_graph(value) -> None:
    st.session_state.last_error = None
    try:
        with st.spinner("智能体正在解析行程、查询天气并检查清单..."):
            result = st.session_state.graph.invoke(value, config=config())
        capture_result(result)
    except Exception as exc:
        st.session_state.last_error = str(exc)


def reset_trip() -> None:
    st.session_state.graph = build_graph()
    st.session_state.thread_id = str(uuid4())
    st.session_state.result = None
    st.session_state.pending_interrupt = None
    st.session_state.packed = {}
    st.session_state.last_error = None


def render_sidebar() -> None:
    with st.sidebar:
        st.header("🧳 旅行小助手")
        st.caption("LangGraph 多节点智能体 · Open-Meteo 真实天气")
        st.divider()
        st.markdown(
            """
            **使用方法**

            1. 输入完整行程并生成清单
            2. 用复选框标记已经打包的物品
            3. 在下方追加活动、同行人员等信息
            4. 智能体会保留原清单并增量修改
            """
        )
        st.divider()
        if st.button("新建行程", use_container_width=True, type="secondary"):
            reset_trip()
            st.rerun()
        st.caption(f"当前会话：{st.session_state.thread_id[:8]}")


def render_trip_input() -> None:
    st.title("旅行小助手")
    st.write(
        "告诉我从哪里出发、去哪里、待多久、有哪些活动，我会结合真实天气生成个性化清单。"
        "如果同时说出出发地和目的地，会自动查询 12306 车次。"
    )
    with st.form("initial_trip_form", clear_on_submit=False):
        trip = st.text_area(
            "行程描述",
            placeholder="例如：这周五从北京去上海，待3天，参加行业展会，晚上可能有同行聚餐。",
            height=130,
        )
        submitted = st.form_submit_button("生成车次信息和所需物品", type="primary", use_container_width=True)
    if submitted:
        if not trip.strip():
            st.warning("请先描述你的行程。")
        else:
            st.session_state.packed = {}
            invoke_graph(initial_state(trip.strip()))
            st.rerun()


def render_weather(state: TravelState) -> None:
    weather = state.get("weather") or {}
    if not weather:
        return
    st.subheader("🌦️ 目的地天气")
    location = weather.get("resolved_location") or state.get("destination") or "未知"
    if weather.get("temp_min_c") is not None and weather.get("temp_max_c") is not None:
        temperature = f"{weather['temp_min_c']}~{weather['temp_max_c']}°C"
    else:
        temperature = f"{weather.get('temp_c', '--')}°C"
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("定位城市", location)
    col2.metric("温度范围", temperature)
    col3.metric("降水概率", f"{weather.get('rain_prob', 0)}%")
    col4.metric("预计降水", f"{weather.get('precipitation_sum_mm', '--')} mm")
    st.info(
        f"**{weather.get('condition', '天气待定')}**  ·  "
        f"预报日期 {state.get('start_date', '待定')}  ·  "
        f"数据来源 {weather.get('source', '用户提供')}"
    )
    if weather.get("risk_note"):
        st.warning(weather["risk_note"])


def render_trip_summary(state: TravelState) -> None:
    companions = "、".join(state.get("companions", [])) or "无"
    st.subheader("📍 行程概览")
    col1, col2, col3, col4, col5 = st.columns(5)
    origin = state.get("origin")
    col1.metric("出发地", origin or "未提供")
    col2.metric("目的地", state.get("destination") or "待确认")
    col3.metric("行程天数", f"{state.get('duration_days', 1)} 天")
    col4.metric("出行人数", f"{state.get('travelers_count', 1)} 人")
    col5.metric("完整性置信度", f"{state.get('confidence', 0)}%")
    st.caption(
        f"日期：{state.get('start_date') or '待定'} 至 {state.get('end_date') or '待定'}"
        f"　｜　同行：{companions}"
    )


def render_trains(state: TravelState) -> None:
    status = state.get("train_status", "skipped")
    if status == "skipped":
        return
    st.subheader("🚄 车次查询（12306）")
    origin = state.get("origin") or "未知"
    destination = state.get("destination") or "未知"
    train_date = state.get("start_date") or "待定"
    st.caption(
        f"{origin} → {destination}  ·  出发日期 {train_date}  ·  "
        "数据来源 12306"
    )
    if status == "failed":
        st.warning(
            f"未能从 12306 获取 {origin} → {destination}（{train_date}）的车次信息。"
            "可能是网络问题、站点名未匹配或 12306 反爬限制，请稍后重试或到 12306 官网查询。"
        )
        return
    trains = state.get("train_results") or []
    if not trains:
        st.info("未查询到匹配车次。")
        return

    st.success(f"共查询到 {len(trains)} 趟车次")
    rows = []
    for train in trains:
        rows.append(
            {
                "车次": train.get("train_number", ""),
                "出发站": train.get("from_station", ""),
                "到达站": train.get("to_station", ""),
                "出发时间": train.get("departure_time", ""),
                "到达时间": train.get("arrival_time", ""),
                "历时": train.get("duration", ""),
                "可购票": "是" if train.get("can_buy") == "Y" else "否",
                "商务座": train.get("business_seat") or "--",
                "特等座": train.get("special_seat") or "--",
                "一等座": train.get("first_seat") or "--",
                "二等座": train.get("second_seat") or "--",
                "高级软卧": train.get("advanced_soft_sleeper") or "--",
                "软卧": train.get("soft_sleeper") or "--",
                "硬卧": train.get("hard_sleeper") or "--",
                "软座": train.get("soft_seat") or "--",
                "硬座": train.get("hard_seat") or "--",
                "无座": train.get("no_seat") or "--",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_packing_list(state: TravelState) -> None:
    st.subheader("✅ 打包清单")
    packing = state.get("packing_list", {})
    total = sum(len(packing.get(category, [])) for category in CATEGORIES)
    packed_count = sum(
        bool(st.session_state.packed.get(item_key(category, item["name"])))
        for category in CATEGORIES
        for item in packing.get(category, [])
    )
    progress = packed_count / total if total else 0.0
    st.progress(progress, text=f"已打包 {packed_count}/{total} 项")

    columns = st.columns(2)
    visible_index = 0
    for category in CATEGORIES:
        items = packing.get(category, [])
        if not items:
            continue
        icon, label = CATEGORY_META[category]
        with columns[visible_index % 2].container(border=True):
            st.markdown(f"### {icon} {label}")
            for item in items:
                key = item_key(category, item["name"])
                checked = st.checkbox(
                    f"{item['name']} × {item['quantity']}",
                    value=bool(st.session_state.packed.get(key, False)),
                    key=f"packed_widget:{key}",
                    help=item["reason"],
                )
                st.session_state.packed[key] = checked
                st.caption(item["reason"])
        visible_index += 1


def render_changes_and_issues(state: TravelState) -> None:
    changes = state.get("changes", [])
    issues = state.get("issues", [])
    if changes:
        with st.expander("📝 查看本次修改", expanded=True):
            for change in changes:
                st.write(f"- {change}")
    if issues:
        with st.expander("⚠️ 仍需注意", expanded=True):
            for issue in issues:
                st.write(f"- {issue}")


def render_interrupt() -> None:
    pending = st.session_state.pending_interrupt
    if not pending:
        return
    st.warning(pending.get("message", str(pending)))
    with st.form("interrupt_form", clear_on_submit=True):
        answer = st.text_input("补充信息")
        submitted = st.form_submit_button("提交并继续", type="primary")
    if submitted:
        if not answer.strip():
            st.warning("请输入补充信息。")
        else:
            invoke_graph(Command(resume=answer.strip()))
            st.rerun()


def render_update_form() -> None:
    st.subheader("💬 追加信息")
    st.caption(
        "例如：第二天要演讲；还有一位女助理同行；晚上需要去健身房；"
        "或者补充出发地，如「我从北京出发」，会自动查询车次。"
    )
    with st.form("update_form", clear_on_submit=True):
        update = st.text_area("告诉智能体新的行程信息", height=90)
        submitted = st.form_submit_button("增量更新清单", type="primary", use_container_width=True)
    if submitted:
        if not update.strip():
            st.warning("请输入需要追加的信息。")
        else:
            invoke_graph({"raw_input": update.strip(), "is_update": True})
            st.rerun()


init_session()
render_sidebar()

if st.session_state.last_error:
    st.error("运行失败：" + st.session_state.last_error)

if st.session_state.result is None:
    render_trip_input()
else:
    state = st.session_state.result
    if st.session_state.pending_interrupt:
        st.title("旅行小助手")
        render_interrupt()
    else:
        render_trip_summary(state)
        render_trains(state)
        render_weather(state)
        render_packing_list(state)
        render_changes_and_issues(state)
        st.divider()
        render_update_form()

