# -*- coding: utf-8 -*-
"""SRA 公开活动日历的数据与游戏选择。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..core import bg
from ..core.config import DEFAULTS, cfg

GAMES = {
    "sr": "崩坏：星穹铁道",
    "ys": "原神",
    "zzz": "绝区零",
    "ww": "鸣潮",
    "nte": "异环",
    "ba-cn": "蔚蓝档案（国服）",
    "ba-jp": "蔚蓝档案（日服）",
    "ba-global": "蔚蓝档案（国际服）",
    "ak": "明日方舟",
    "end": "明日方舟：终末地",
    "xtlr": "星塔旅人",
    "infinitynikki": "无限暖暖",
    "gf2": "少女前线2：追放",
    "pgr": "战双帕弥什",
    "czn": "卡厄斯梦境（国际服）",
    "bd2": "棕色尘埃2",
    "nikke": "NIKKE（国际服）",
    "hyrz": "火影忍者",
}
API_URL = "https://starrailassistant.top/api/v1/activity"
BEIJING = timezone(timedelta(hours=8))


def selected_games() -> list[str]:
    entries = cfg.get("game_calendar.games")
    if not isinstance(entries, list):
        entries = DEFAULTS["game_calendar"]["games"]
    return list(dict.fromkeys(key for key in entries if isinstance(key, str) and key in GAMES))


@dataclass(frozen=True)
class Activity:
    name: str
    kind: str
    description: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class GameCalendar:
    version: str
    activities: tuple[Activity, ...]


def _beijing_time(value: str) -> datetime:
    # 中文接口的无偏移时间按北京时间显示。带偏移的 ISO 时间按原偏移转换。
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BEIJING)
    return dt.astimezone(BEIJING)


def parse_calendar(data: dict) -> GameCalendar:
    if not isinstance(data, dict) or not isinstance(data.get("activities"), list):
        raise ValueError("活动接口没有返回有效列表")
    activities = []
    for row in data["activities"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            continue
        try:
            start, end = _beijing_time(row.get("startTime")), _beijing_time(row.get("endTime"))
        except (ValueError, TypeError):
            continue
        if end >= start:
            activities.append(Activity(row["name"].strip(), str(row.get("kind") or ""),
                                       str(row.get("description") or ""), start, end))
    if data["activities"] and not activities:
        raise ValueError("活动接口中的日期无法读取")
    # 同一活动可能有不同开放档期；仅合并完全重复的记录。
    return GameCalendar(str(data.get("version") or ""), tuple(dict.fromkeys(activities)))


def fetch_calendar(game: str) -> GameCalendar:
    response = bg.http_client().get(f"{API_URL}/{game}.json", follow_redirects=True)
    response.raise_for_status()
    return parse_calendar(response.json())
