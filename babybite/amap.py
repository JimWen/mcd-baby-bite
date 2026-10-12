"""高德地图 MCP 联动：天气提醒、步行到店时间、导航唤端链接（可选，需 AMAP_MAPS_API_KEY）。"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from itertools import zip_longest
from typing import Optional

from .errors import BabyBiteError
from .mcp_client import McpHttpClient, OfflineClient

AMAP_MCP_URL = "https://mcp.amap.com/mcp"
BAD_WEATHER = ("雨", "雪", "雷", "暴", "冰雹", "沙尘")
WALK_MAX_MIN = 20
AMAP_MAX_STORES = 3
PLAY_KEYWORDS = ("儿童乐园", "公园")
PLAY_RADIUS = 2000


class Throttled:
    """高德文本工具调用限速；仅对 QPS 超限错误做有限重试。"""

    def __init__(self, client, interval=0.35, sleep=time.sleep, clock=time.monotonic,
                 attempts=3, backoff=1.0):
        self._client = client
        self._interval = max(0.0, interval)
        self._sleep = sleep
        self._clock = clock
        self._attempts = max(1, attempts)
        self._backoff = max(0.0, backoff)
        self._last_call = None

    def call_tool_text(self, name: str, args: dict) -> str:
        for attempt in range(self._attempts):
            if self._last_call is not None:
                remaining = self._interval - (self._clock() - self._last_call)
                if remaining > 0:
                    self._sleep(remaining)
            self._last_call = self._clock()
            try:
                return self._client.call_tool_text(name, args)
            except BabyBiteError as exc:
                if "CUQPS_HAS_EXCEEDED_THE_LIMIT" not in str(exc) or attempt + 1 == self._attempts:
                    raise
                self._sleep(self._backoff)


@dataclass(frozen=True)
class PlaySpot:
    name: str
    kind: str
    walk_minutes: int
    walk_meters: int
    address: str


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


def nearby_play(client, store_location: str, limit: int = 3) -> list[PlaySpot]:
    """周边 POI 按品牌去重、交替取前四个路由，推荐中尽量保留公园。"""
    if limit <= 0:
        return []
    groups, seen, brands = [], set(), set()
    for keyword in PLAY_KEYWORDS:
        pois = _json(client, "maps_around_search", {
            "location": store_location, "keywords": keyword, "radius": str(PLAY_RADIUS),
        }).get("pois") or []
        group = []
        for poi in pois:
            poi_id, name = poi.get("id"), poi.get("name") or ""
            typecode = str(poi.get("typecode") or "")
            if not poi_id or poi_id in seen or not name or "-" in name or not typecode.startswith(("0805", "11")):
                continue
            brand = re.sub(r"(?:\([^()]*\)|（[^（）]*）)$", "", name).strip()
            if brand in brands:
                continue
            seen.add(poi_id)
            brands.add(brand)
            group.append(poi)
        groups.append(group)
    candidates = [poi for pair in zip_longest(*groups) for poi in pair if poi is not None][:4]
    spots = []
    for poi in candidates:
        location = _json(client, "maps_search_detail", {"id": poi["id"]}).get("location")
        if not location:
            continue
        minutes, meters = walking(client, store_location, location)
        if minutes is None or meters is None:
            continue
        kind = "游乐场" if str(poi["typecode"]).startswith("0805") else "公园"
        spots.append(PlaySpot(poi["name"], kind, minutes, meters, poi.get("address") or ""))
    spots.sort(key=lambda spot: spot.walk_minutes)
    result = spots[:limit]
    if result and not any(spot.kind == "公园" for spot in result):
        park = next((spot for spot in spots if spot.kind == "公园"), None)
        if park is not None:
            result[-1] = park
            result.sort(key=lambda spot: spot.walk_minutes)
    return result
