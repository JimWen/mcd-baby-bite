"""高德地图 MCP 联动：天气提醒、步行到店时间、导航唤端链接（可选，需 AMAP_MAPS_API_KEY）。"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from .errors import BabyBiteError
from .mcp_client import McpHttpClient, OfflineClient

AMAP_MCP_URL = "https://mcp.amap.com/mcp"
BAD_WEATHER = ("雨", "雪", "雷", "暴", "冰雹", "沙尘")
WALK_MAX_MIN = 20
AMAP_MAX_STORES = 3


@dataclass(frozen=True)
class StoreRoute:
    store_code: str
    poi_name: str
    walk_minutes: Optional[int]
    walk_meters: Optional[int]
    location: Optional[str] = None


def amap_client_from_env(offline: bool = False):
    if offline:
        return OfflineClient()
    key = os.environ.get("AMAP_MAPS_API_KEY", "").strip()
    if not key:
        return None
    return McpHttpClient(f"{AMAP_MCP_URL}?key={urllib.parse.quote(key)}", secrets=(key,), write_tools=frozenset())


def _json(client, name: str, args: dict) -> dict:
    text = client.call_tool_text(name, args)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise BabyBiteError(f"高德 {name} 返回无法解析：{text[:100]}") from None
    return data if isinstance(data, dict) else {}


def weather_notice(client, city: str, date: Optional[str]) -> Optional[str]:
    forecasts = _json(client, "maps_weather", {"city": city}).get("forecasts") or []
    day = next((f for f in forecasts if date and f.get("date") == date), forecasts[0] if forecasts else None)
    if not day:
        return None
    weather = day.get("dayweather", "")
    text = f"高德天气：{day.get('date')} 白天{weather}，{day.get('daytemp')}℃。"
    if any(word in weather for word in BAD_WEATHER):
        text += "带娃出门不便，可以考虑得来速或麦乐送。"
    return text


def geocode(client, address: str, city: str) -> Optional[str]:
    results = _json(client, "maps_geo", {"address": address, "city": city}).get("results") or []
    return results[0].get("location") if results else None


def store_location(client, store_name: str, city: str):
    """按门店名称搜 POI 再取详情坐标；比用门店地址做地理编码准确得多。"""
    pois = _json(client, "maps_text_search", {"keywords": store_name, "city": city, "citylimit": True}).get("pois") or []
    pois = [p for p in pois if "麦当劳" in p.get("name", "")]
    if not pois:
        return None
    detail = _json(client, "maps_search_detail", {"id": pois[0]["id"]})
    location = detail.get("location")
    return (detail.get("name") or pois[0]["name"], location) if location else None


def walking(client, origin: str, destination: str):
    paths = (_json(client, "maps_direction_walking", {"origin": origin, "destination": destination})
             .get("route") or {}).get("paths") or []
    if not paths:
        return None, None
    return max(1, math.ceil(int(paths[0]["duration"]) / 60)), int(paths[0]["distance"])


def navi_url(client, location: str) -> Optional[str]:
    lon, lat = location.split(",")
    text = client.call_tool_text("maps_schema_navi", {"lon": lon, "lat": lat}).strip()
    return text if text.startswith(("amapuri://", "http")) else None


def route_for_store(client, store, origin: str, city: str) -> StoreRoute:
    found = store_location(client, store.name, city)
    if not found:
        return StoreRoute(store.code, store.name, None, None)
    poi_name, location = found
    minutes, meters = walking(client, origin, location)
    return StoreRoute(store.code, poi_name, minutes, meters, location)
