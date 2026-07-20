from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from http.cookiejar import CookieJar
from typing import Any
from urllib.parse import urlencode, unquote
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


CITY_NAMES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "南京",
    "武汉",
    "西安",
    "哈尔滨",
    "长春",
    "沈阳",
    "三亚",
    "香港",
    "东京",
    "首尔",
    "新加坡",
    "伦敦",
    "巴黎",
    "纽约",
)


class DeepSeekConfigurationError(RuntimeError):
    """Raised when the required DeepSeek credentials are unavailable."""


class DeepSeekRequestError(RuntimeError):
    """Raised when DeepSeek cannot successfully parse a trip request."""


def require_deepseek_api_key() -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise DeepSeekConfigurationError(
            "未配置 DEEPSEEK_API_KEY，智能体无法启动。请复制 .env.example 为 .env，"
            "填入你自己的 DeepSeek API Key 后重新运行。"
        )
    return api_key

ACTIVITY_KEYWORDS = {
    "商务会议": ("会议", "客户", "商务", "见客户"),
    "行业展会": ("展会", "展览"),
    "演讲": ("演讲", "汇报", "路演", "上台"),
    "聚餐": ("饭局", "聚餐", "晚宴"),
    "健身": ("健身", "健身房"),
    "游泳": ("游泳", "泳池"),
    "休闲观光": ("旅游", "观光", "逛", "游玩"),
}

SPECIAL_KEYWORDS = {
    "见重要客户": ("重要客户", "关键客户"),
    "正式场合": ("正装", "正式晚宴", "正式场合"),
    "需要笔记本电脑": ("笔记本电脑", "电脑"),
    "户外活动": ("户外", "徒步", "登山"),
}

COMPANION_ROLES = (
    "女助理",
    "男助理",
    "助理",
    "秘书",
    "同事",
    "妻子",
    "丈夫",
    "女友",
    "男友",
    "朋友",
    "家人",
)

CITY_SEARCH_ALIASES = {
    "安庆": "Anqing",
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "南京": "Nanjing",
    "武汉": "Wuhan",
    "西安": "Xian",
    "哈尔滨": "Harbin",
}


# 12306 train ticket query configuration.
TRAIN_INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"
TRAIN_STATION_JS_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
TRAIN_QUERY_URL = "https://kyfw.12306.cn/otn/leftTicket/queryZ"
TRAIN_QUERY_FALLBACK_URL = "https://kyfw.12306.cn/otn/leftTicket/query"
TRAIN_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": TRAIN_INIT_URL,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_station_code_cache: dict[str, str] | None = None


def _next_weekday(base: date, weekday: int, next_week: bool = False) -> date:
    start = base + timedelta(days=(7 - base.weekday()) if next_week else 0)
    delta = (weekday - start.weekday()) % 7
    if not next_week and delta == 0 and start == base:
        return base
    return start + timedelta(days=delta)


def _parse_relative_date(text: str, today: date) -> str | None:
    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    match = re.search(r"(下周|这周|本周)?(?:周|星期)([一二三四五六日天])", text)
    if match:
        next_week = match.group(1) == "下周"
        return _next_weekday(today, weekday_map[match.group(2)], next_week).isoformat()

    offsets = {"今天": 0, "明天": 1, "后天": 2}
    for token, offset in offsets.items():
        if token in text:
            return (today + timedelta(days=offset)).isoformat()

    explicit = re.search(r"(?:(\d{4})[年/-])?(\d{1,2})[月/-](\d{1,2})日?", text)
    if explicit:
        year = int(explicit.group(1) or today.year)
        return date(year, int(explicit.group(2)), int(explicit.group(3))).isoformat()
    return None


def _extract_json(content: str) -> dict[str, Any]:
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1)
    else:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output is not a JSON object")
    return parsed


_ORIGIN_EXCLUDE_TOKENS = {
    "参加", "出差", "旅游", "开会", "办事", "这里", "那里",
    "本地", "外地", "家里", "公司", "学校",
    "今天", "明天", "后天", "大后天", "下周", "这周", "本周",
}


def _looks_like_date_word(candidate: str) -> bool:
    if candidate in _ORIGIN_EXCLUDE_TOKENS:
        return True
    if re.match(r"周[一二三四五六日天]$", candidate):
        return True
    if re.match(r"星期[一二三四五六日天]$", candidate):
        return True
    return False


def _extract_origin(text: str, destination: str | None) -> str | None:
    """Extract origin (出发地) from text. Returns None if no origin is mentioned."""
    # Pattern 1: 从X(出发)?去/到/前往/飞往/开往/至 (non-greedy to avoid capturing 出发)
    match = re.search(
        r"从([\u4e00-\u9fff]{2,8}?)(?:出发)?(?:去|到|前往|飞往|开往|至)",
        text,
    )
    if match:
        candidate = match.group(1)
        if candidate and not _looks_like_date_word(candidate) and candidate != destination:
            return candidate

    # Pattern 2: X(出发)?到/去Y where Y is the destination (non-greedy)
    if destination:
        match = re.search(
            rf"([\u4e00-\u9fff]{{2,8}}?)(?:出发)?(?:到|去|飞往|前往|开往|至){re.escape(destination)}",
            text,
        )
        if match:
            candidate = match.group(1)
            if (
                candidate
                and not _looks_like_date_word(candidate)
                and candidate != destination
                and not (destination and candidate.startswith(destination))
                and not (destination and destination.startswith(candidate))
            ):
                return candidate
    return None


def parse_with_deepseek(text: str, today: date) -> dict[str, Any] | None:
    api_key = require_deepseek_api_key()
    try:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=api_key,
            temperature=0,
            timeout=20,
            max_retries=1,
        )
        prompt = f"""
今天是 {today.isoformat()}。从下面的中文行程中只提取明确出现或可直接推断的信息。
返回一个 JSON 对象，字段为 origin, destination, start_date, end_date, duration_days,
travelers_count, companions, activities, special_events, constraints。origin 是出发地
（用户从哪里出发），destination 是目的地。travelers_count
是包括用户本人在内的总人数，companions 是同行者身份列表。日期使用 YYYY-MM-DD；未知标量用 null，
未知列表用 []。不要输出 JSON 以外的内容。
行程：{text}
""".strip()
        response = model.invoke(prompt)
        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _extract_json(content)
        if parsed is None:
            raise DeepSeekRequestError("DeepSeek 返回了无法解析的内容，请稍后重试。")
        return parsed
    except DeepSeekRequestError:
        raise
    except Exception as exc:
        raise DeepSeekRequestError(
            "DeepSeek 调用失败，请检查 API Key、账户余额和网络连接后重试。"
        ) from exc


def parse_trip_info(text: str, today: date | None = None, use_llm: bool = True) -> dict[str, Any]:
    today = today or date.today()
    llm_result = parse_with_deepseek(text, today) if use_llm else None

    # Destination extraction: prefer a known city that appears right after a
    # trigger word (去/到/前往/...). This avoids picking the origin city when
    # the user says "从北京去上海".
    destination = None
    for city in CITY_NAMES:
        if re.search(rf"(?:去|飞往|前往|到|开往|至){re.escape(city)}", text):
            destination = city
            break
    if destination is None:
        destination_match = re.search(
            r"(?:去|飞往|前往|到)([\u4e00-\u9fff]{2,8})(?=[，,。.!！？\s]|$)",
            text,
        )
        if destination_match:
            candidate = destination_match.group(1)
            if candidate not in {"参加", "出差", "旅游", "开会", "办事"}:
                destination = candidate
    if destination is None:
        destination = next((city for city in CITY_NAMES if city in text), None)

    origin = _extract_origin(text, destination)
    start_date = _parse_relative_date(text, today)
    duration_match = re.search(r"(?:待|停留|出差|共)\s*(\d+)\s*(?:天|日)", text)
    if not duration_match:
        duration_match = re.search(r"(?<![年月\d])(\d+)\s*天", text)
    duration_days = int(duration_match.group(1)) if duration_match else None

    companions: list[str] = []
    for role in COMPANION_ROLES:
        role_match = re.search(
            rf"(?:和|与|有(?:一|1)?(?:个|位|名)?|带(?:一|1)?(?:个|位|名)?)?{role}"
            rf".*?(?:一起去|同行|跟着我|随行|陪同|一起出行)",
            text,
        )
        if role_match:
            companions.append(role)
    # Prefer the more specific role when both e.g. '女助理' and '助理' match.
    companions = [
        role
        for role in companions
        if not any(role != other and role in other for other in companions)
    ]

    travelers_count = None
    count_match = re.search(r"(?:我们|一共|总共|共)?\s*(\d+)\s*(?:个人|人)(?:一起|同行|出行|去)?", text)
    if count_match:
        travelers_count = max(1, int(count_match.group(1)))
    elif companions:
        travelers_count = 1 + len(companions)

    activities = [
        activity
        for activity, keywords in ACTIVITY_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    special_events = [
        event
        for event, keywords in SPECIAL_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    constraints: list[str] = []
    if any(token in text for token in ("不带厚外套", "不要厚外套", "不想带厚外套")):
        constraints.append("不带厚外套")
    if any(token in text for token in ("只带登机箱", "不托运")):
        constraints.append("仅随身行李")

    result: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "end_date": None,
        "duration_days": duration_days,
        "travelers_count": travelers_count,
        "companions": companions,
        "activities": activities,
        "special_events": special_events,
        "constraints": constraints,
    }
    if llm_result:
        for key in ("origin", "destination", "start_date", "end_date", "duration_days", "travelers_count"):
            if llm_result.get(key) not in (None, ""):
                result[key] = llm_result[key]
        for key in ("companions", "activities", "special_events", "constraints"):
            if isinstance(llm_result.get(key), list):
                result[key] = list(dict.fromkeys(result[key] + llm_result[key]))

    if result["duration_days"] and result["start_date"] and not result["end_date"]:
        start = date.fromisoformat(result["start_date"])
        result["end_date"] = (start + timedelta(days=result["duration_days"] - 1)).isoformat()
    elif result["start_date"] and result["end_date"] and not result["duration_days"]:
        start = date.fromisoformat(result["start_date"])
        end = date.fromisoformat(result["end_date"])
        result["duration_days"] = max(1, (end - start).days + 1)
    return result


def get_mock_weather(destination: str | None, start_date: str | None) -> dict[str, Any] | None:
    """Return deterministic seasonal weather, or None to exercise the fallback path."""
    if not destination or destination not in CITY_NAMES:
        return None
    month = date.fromisoformat(start_date).month if start_date else date.today().month

    profiles = {
        "上海": {"winter": (7, 60, "阴雨"), "summer": (31, 65, "多云有阵雨")},
        "北京": {"winter": (-5, 10, "晴冷"), "summer": (31, 30, "晴间多云")},
        "哈尔滨": {"winter": (-18, 15, "晴冷"), "summer": (25, 35, "多云")},
        "三亚": {"winter": (24, 20, "晴"), "summer": (31, 55, "雷阵雨")},
        "伦敦": {"winter": (6, 65, "小雨"), "summer": (20, 45, "多云")},
    }
    default = {"winter": (8, 30, "多云"), "summer": (29, 40, "多云")}
    season = "winter" if month in (11, 12, 1, 2, 3) else "summer"
    temp, rain_prob, condition = profiles.get(destination, default)[season]
    return {
        "temp_c": temp,
        "rain_prob": rain_prob,
        "condition": condition,
        "source": "mock",
        "needs_umbrella": rain_prob >= 50,
        "needs_sunscreen": temp >= 25,
        "needs_warm_layer": temp <= 10,
    }


WEATHER_CODE_LABELS = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴（模型提示局地冰雹风险）",
    99: "强雷暴（模型提示局地冰雹风险）",
}


def _fetch_json(base_url: str, params: dict[str, Any], timeout: int = 8) -> dict[str, Any]:
    url = f"{base_url}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "TravelPackingAssistant/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Weather service returned an invalid response")
    return payload


def get_open_meteo_weather(
    destination: str | None,
    start_date: str | None,
) -> dict[str, Any] | None:
    """Fetch real forecast data from Open-Meteo without an API key."""
    if not destination or not start_date:
        return None
    try:
        candidates: list[dict[str, Any]] = []
        for query in dict.fromkeys((CITY_SEARCH_ALIASES.get(destination), destination)):
            if not query:
                continue
            geocoding = _fetch_json(
                "https://geocoding-api.open-meteo.com/v1/search",
                {
                    "name": query,
                    "count": 10,
                    "language": "zh",
                    "format": "json",
                },
            )
            candidates = geocoding.get("results") or []
            if candidates:
                break
        if not candidates:
            return None
        location = next(
            (
                item
                for item in candidates
                if item.get("country_code") == "CN"
                and item.get("feature_code") in {"PPLC", "PPLA", "PPLA2"}
            ),
            next(
                (item for item in candidates if item.get("country_code") == "CN"),
                candidates[0],
            ),
        )
        forecast = _fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,precipitation_sum"
                ),
                "hourly": "weather_code,precipitation_probability,precipitation",
                "timezone": "Asia/Shanghai",
                "start_date": start_date,
                "end_date": start_date,
            },
        )
        daily = forecast.get("daily") or {}
        dates = daily.get("time") or []
        if start_date not in dates:
            return None
        index = dates.index(start_date)
        temp_max = float(daily["temperature_2m_max"][index])
        temp_min = float(daily["temperature_2m_min"][index])
        rain_prob = int(daily["precipitation_probability_max"][index] or 0)
        precipitation_sum = float(daily["precipitation_sum"][index] or 0)
        weather_code = int(daily["weather_code"][index])
        hourly = forecast.get("hourly") or {}
        hourly_times = hourly.get("time") or []
        hourly_codes = [int(code) for code in (hourly.get("weather_code") or [])]
        thunderstorm_hours = [
            hourly_times[i][11:16]
            for i, code in enumerate(hourly_codes)
            if code in {95, 96, 99} and i < len(hourly_times)
        ]
        hail_risk_hours = [
            hourly_times[i][11:16]
            for i, code in enumerate(hourly_codes)
            if code in {96, 99} and i < len(hourly_times)
        ]
        rain_hours = sum(
            code in set(range(51, 68)) | {80, 81, 82, 95, 96, 99}
            for code in hourly_codes
        )
        if thunderstorm_hours:
            condition = "雷阵雨，存在短时强对流风险"
        elif rain_hours:
            condition = "有雨"
        else:
            condition = WEATHER_CODE_LABELS.get(weather_code, f"天气代码 {weather_code}")

        risk_note = None
        if hail_risk_hours:
            risk_note = (
                f"模型仅在 {', '.join(hail_risk_hours)} 标记局地冰雹可能，"
                "属于短时强对流风险，不表示全天会下冰雹。"
            )
        resolved_name = location.get("name") or destination
        admin = location.get("admin1")
        return {
            # Packing decisions use the daily minimum to avoid under-packing layers.
            "temp_c": round(temp_min, 1),
            "temp_min_c": round(temp_min, 1),
            "temp_max_c": round(temp_max, 1),
            "rain_prob": rain_prob,
            "precipitation_sum_mm": round(precipitation_sum, 1),
            "condition": condition,
            "thunderstorm_hours": thunderstorm_hours,
            "hail_risk_hours": hail_risk_hours,
            "risk_note": risk_note,
            "source": "Open-Meteo",
            "resolved_location": f"{admin} {resolved_name}".strip() if admin else resolved_name,
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "needs_umbrella": rain_prob >= 50 or weather_code in range(51, 68),
            "needs_sunscreen": temp_max >= 25 and weather_code <= 3,
            "needs_warm_layer": temp_min <= 10,
        }
    except (KeyError, TypeError, ValueError, OSError):
        return None


def get_weather(destination: str | None, start_date: str | None) -> dict[str, Any] | None:
    """Use real weather first; let the graph request manual input on failure."""
    return get_open_meteo_weather(destination, start_date)


def parse_manual_weather(text: str) -> dict[str, Any] | None:
    temp_match = re.search(r"(-?\d+)\s*(?:度|℃|°C)?", text, re.IGNORECASE)
    if not temp_match:
        return None
    temp = int(temp_match.group(1))
    rain = any(token in text for token in ("雨", "降水", "阵雨", "雷雨"))
    rain_prob_match = re.search(r"(?:降水|下雨|雨).*?(\d{1,3})\s*%", text)
    rain_prob = int(rain_prob_match.group(1)) if rain_prob_match else (70 if rain else 20)
    return {
        "temp_c": temp,
        "rain_prob": rain_prob,
        "condition": "用户提供：" + text.strip(),
        "source": "user",
        "needs_umbrella": rain_prob >= 50,
        "needs_sunscreen": temp >= 25 and not rain,
        "needs_warm_layer": temp <= 10,
    }


def _fetch_station_codes() -> dict[str, str]:
    """Fetch and cache the 12306 station name -> telecode mapping."""
    global _station_code_cache
    if _station_code_cache is not None:
        return _station_code_cache
    try:
        request = Request(TRAIN_STATION_JS_URL, headers=TRAIN_BROWSER_HEADERS)
        with urlopen(request, timeout=10) as response:
            content = response.read().decode("utf-8", errors="ignore")
        match = re.search(r"station_names\s*=\s*'([^']+)'", content)
        if not match:
            return {}
        cache: dict[str, str] = {}
        for entry in match.group(1).split("@"):
            parts = entry.split("|")
            if len(parts) >= 3 and parts[1]:
                cache[parts[1]] = parts[2]
        _station_code_cache = cache
        return cache
    except (OSError, ValueError):
        return {}


def _resolve_station_code(stations: dict[str, str], name: str) -> str | None:
    """Resolve a city/station name to a 12306 telecode."""
    if not name or not stations:
        return None
    if name in stations:
        return stations[name]
    # Try prefix match (e.g., "北京" matches "北京南", "北京北")
    candidates = [n for n in stations if n.startswith(name)]
    if not candidates:
        return None
    # Prefer shorter names (city-level stations) then alphabetical for determinism.
    candidates.sort(key=lambda n: (len(n), n))
    return stations[candidates[0]]


def _parse_train_result(item: str, station_map: dict[str, str]) -> dict[str, Any]:
    """Parse a single 12306 leftTicket result string into a dict.

    The 12306 API now URL-encodes each result string and prepends an
    encrypted blob as field 0, which shifts every subsequent field by one
    compared to the legacy format. Field layout (after URL-decoding):
        0: encrypted blob
        1: action (e.g. 预订)
        2: train_id (e.g. 240000G54700)
        3: train_number (e.g. G547)
        4: from_station_code
        5: to_station_code
        6: from_station_code (repeat)
        7: to_station_code (repeat)
        8: departure_time
        9: arrival_time
        10: duration
        11: can_buy (Y/N)
        12: encrypted blob
        13: date (YYYYMMDD)
        20: business_seat (商务座)
        27: special_seat (特等座)
        30: first_seat (一等座)
        31: second_seat (二等座)
        32: advanced_soft_sleeper (高级软卧)
        33: soft_sleeper (软卧/动卧)
        34: move_sleeper (动卧)
        35: hard_sleeper (硬卧)
        36: soft_seat (软座)
        37: hard_seat (硬座)
        38: no_seat (无座)
        39: other_seat (其他)
    """
    # The API URL-encodes the whole result string (including the pipe
    # separators and base64 blobs). Decode it first so split("|") works.
    decoded = unquote(item)
    parts = decoded.split("|")

    def resolve(code: str) -> str:
        return station_map.get(code, code) if code else ""

    def at(index: int) -> str:
        return parts[index] if index < len(parts) else ""

    def seat_label(index: int) -> str:
        value = at(index)
        return value if value and value != "无" else "无"

    return {
        "train_number": at(3),
        "from_station": resolve(at(4)),
        "to_station": resolve(at(5)),
        "departure_time": at(8),
        "arrival_time": at(9),
        "duration": at(10),
        "can_buy": at(11),
        "note": at(12),
        "business_seat": seat_label(20),
        "special_seat": seat_label(27),
        "first_seat": seat_label(30),
        "second_seat": seat_label(31),
        "advanced_soft_sleeper": seat_label(32),
        "soft_sleeper": seat_label(33),
        "move_sleeper": seat_label(34),
        "hard_sleeper": seat_label(35),
        "soft_seat": seat_label(36),
        "hard_seat": seat_label(37),
        "no_seat": seat_label(38),
        "other_seat": seat_label(39),
    }


def _query_train_endpoint(url: str, from_code: str, to_code: str, train_date: str) -> dict[str, Any] | None:
    """Query a single 12306 endpoint and return parsed payload or None.

    12306 requires a valid session: we first visit the init page to obtain
    cookies (JSESSIONID, BIGipServerotn, route) and then issue the query
    with the same cookie jar. The response is UTF-8 with a BOM and the
    result strings are URL-encoded, both of which are handled here and in
    ``_parse_train_result``.
    """
    try:
        cookie_jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        # Step 1: visit the init page to establish a session.
        init_request = Request(TRAIN_INIT_URL, headers=TRAIN_BROWSER_HEADERS)
        opener.open(init_request, timeout=15).read()
        # Step 2: query with the same cookies.
        params = urlencode(
            {
                "leftTicketDTO.train_date": train_date,
                "leftTicketDTO.from_station": from_code,
                "leftTicketDTO.to_station": to_code,
                "purpose_codes": "ADULT",
            }
        )
        query_request = Request(f"{url}?{params}", headers=TRAIN_BROWSER_HEADERS)
        with opener.open(query_request, timeout=15) as response:
            # utf-8-sig strips the BOM that 12306 prepends to JSON responses.
            content = response.read().decode("utf-8-sig", errors="replace")
        payload = json.loads(content)
        if not isinstance(payload, dict) or not payload.get("data"):
            return None
        data = payload["data"]
        if not isinstance(data, dict):
            return None
        return {
            "result": data.get("result") or [],
            "map": data.get("map") or {},
        }
    except (OSError, ValueError, TypeError):
        return None


def query_12306_trains(
    origin: str | None,
    destination: str | None,
    train_date: str | None,
) -> dict[str, Any] | None:
    """Query 12306 for trains from origin to destination on train_date.

    Returns ``{"results": [...], "from_station": str, "to_station": str,
    "train_date": str, "query_url": str}`` on success, or ``None`` on failure.
    """
    if not origin or not destination or not train_date:
        return None
    stations = _fetch_station_codes()
    if not stations:
        return None
    from_code = _resolve_station_code(stations, origin)
    to_code = _resolve_station_code(stations, destination)
    if not from_code or not to_code:
        return None

    payload = _query_train_endpoint(TRAIN_QUERY_URL, from_code, to_code, train_date)
    if payload is None:
        payload = _query_train_endpoint(
            TRAIN_QUERY_FALLBACK_URL, from_code, to_code, train_date
        )
    if payload is None:
        return None

    station_map = payload["map"]
    trains = [
        _parse_train_result(item, station_map)
        for item in payload["result"]
        if isinstance(item, str) and item
    ]
    query_url = (
        f"{TRAIN_INIT_URL}&leftTicketDTO.train_date={train_date}"
        f"&leftTicketDTO.from_station={from_code}"
        f"&leftTicketDTO.to_station={to_code}&purpose_codes=ADULT"
    )
    return {
        "results": trains,
        "from_station": stations.get(origin) and origin or origin,
        "to_station": destination,
        "from_code": from_code,
        "to_code": to_code,
        "train_date": train_date,
        "query_url": query_url,
        "source": "12306",
    }
