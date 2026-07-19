from travel_packing.render import render_console
from travel_packing.state import initial_state


def test_console_render_has_no_markdown_table():
    state = initial_state("后天去安庆")
    state.update(
        {
            "destination": "安庆",
            "start_date": "2026-07-21",
            "end_date": "2026-07-21",
            "weather": {
                "temp_c": 25.3,
                "temp_min_c": 25.3,
                "temp_max_c": 28.5,
                "rain_prob": 98,
                "condition": "雷暴",
                "source": "Open-Meteo",
                "resolved_location": "安徽 安庆市",
            },
            "packing_list": {
                "clothing": [{"name": "日常上衣", "quantity": 1, "reason": "一日行程"}],
                "electronics": [],
                "toiletries": [],
                "documents": [],
                "other": [],
            },
            "confidence": 95,
        }
    )
    output = render_console(state)
    assert "| 类别 |" not in output
    assert "定位城市：安徽 安庆市" in output
    assert "数据来源：Open-Meteo" in output
    assert "- 日常上衣 x1：一日行程" in output
