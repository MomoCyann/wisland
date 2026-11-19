# -*- coding: utf-8 -*-
"""从本地千机链和三个子脚本的日志汇总当天日常。"""
from __future__ import annotations

import ctypes
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

from ..core.config import cfg, expand
from .game_calendar import BEIJING

DEFAULT_ROOT = "D:/mihoyoMOD"
DAILY_GAMES = {"sr": "星铁", "zzz": "绝区零", "ww": "鸣潮"}
LOG_SOURCES = {
    "chain": ("千机链", "千机链/.log", (".log",), ("script_chainer_runner.log*",)),
    "sr": ("星铁 · 三月七助手", "March7thAssistant_full/logs/runs", ("runs", "logs/runs"),
           ("????????-??????-*.log", "????????-??????-*.json")),
    "zzz": ("绝区零 · 一条龙", "ZZZonedragon/.log", (".log",), ("log.txt*",)),
    "ww": ("鸣潮 · OK-WW", "ok-ww/data/apps/ok-ww/working/logs", ("logs", "data/apps/ok-ww/working/logs"), ("ok-script*.log",)),
}
_STAMP = re.compile(r"^\[?(\d\d:\d\d:\d\d)(?:[.,]\d+)?\]")
_DATED = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:[.,]\d+)?")
_CHAIN_GAME = {"崩坏：星穹铁道": "sr", "绝区零": "zzz", "鸣潮": "ww"}
_CHAIN_EVENT = re.compile(r"\[script_runner\.py \d+\] \[[A-Z]+\]: (正在运行|运行结束|游戏或脚本被关闭|取消运行|运行超时) (.+)$")


@dataclass
class Run:
    started: datetime | None = None
    ended: datetime | None = None
    state: str = ""


@dataclass
class Daily:
    activity: str = "暂无记录"
    completed: datetime | None = None
    stamina: str = "暂无刷本记录"
    run: Run = field(default_factory=Run)
    activity_full: bool | None = None
    reminder_detail: str = ""


@dataclass(frozen=True)
class LogLocation:
    folder: Path
    found: bool


def log_settings() -> tuple[str, dict[str, str]]:
    root = str(cfg.get("game_daily.root") or "").strip()
    folders = cfg.get("game_daily.folders")
    if not isinstance(folders, dict):
        return root, {}
    return root, {key: path.strip() for key, path in folders.items()
                  if key in LOG_SOURCES and isinstance(path, str) and path.strip()}


def _root_candidates(root: str) -> list[Path]:
    if root:
        return [Path(expand(root)).expanduser()]
    roots = [Path(DEFAULT_ROOT)]
    if os.name == "nt" and hasattr(os, "listdrives"):
        try:
            for drive in os.listdrives():
                if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)) == 3:  # DRIVE_FIXED
                    roots.append(Path(drive) / "mihoyoMOD")
        except OSError:
            pass
    return list(dict.fromkeys(roots))


def _has_logs(folder: Path, patterns: tuple[str, ...]) -> bool:
    try:
        return any(path.is_file() for pattern in patterns for path in folder.glob(pattern))
    except (OSError, ValueError):
        return False


def locate_logs(root: str = "", folders: dict[str, str] | None = None) -> dict[str, LogLocation]:
    """只探测已知的目录结构。单独指定路径后，以该路径为准。"""
    roots = _root_candidates(root)
    locations = {}
    for key, (_, relative, subdirs, patterns) in LOG_SOURCES.items():
        custom = (folders or {}).get(key)
        if custom:
            folder = Path(expand(custom)).expanduser()
            candidates = [folder, *(folder / subdir for subdir in subdirs)]
        else:
            candidates = [base / relative for base in roots]
        match = next((candidate for candidate in candidates if _has_logs(candidate, patterns)), None)
        locations[key] = LogLocation(match or candidates[0], match is not None)
    return locations


def daily_start(now: datetime) -> datetime:
    local = now.astimezone(BEIJING)
    return datetime.combine((local - timedelta(hours=4)).date(), time(4), BEIJING)


def daily_reminders_due(now: datetime) -> bool:
    return now >= daily_start(now) + timedelta(minutes=1)


def daily_reminder(daily: Daily, now: datetime) -> str:
    if not daily_reminders_due(now) or daily.activity_full is True:
        return ""
    if daily.activity == "找不到日志":
        return daily.activity
    if daily.reminder_detail:
        return daily.reminder_detail
    if daily.run.started and not daily.run.ended:
        return "已启动 · 活跃度待确认"
    if daily.activity_full is False:
        return "每日活跃度未满"
    if not (daily.run.started or daily.run.ended or daily.completed or daily.activity != "暂无记录"):
        return "未见运行记录"
    return "活跃度未确认"


@lru_cache(maxsize=32)
def _contents(path: Path, modified: int, size: int) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _read(path: Path, since: datetime):
    try:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, BEIJING)
        if modified >= since:
            return _contents(path, stat.st_mtime_ns, stat.st_size), modified
    except OSError:
        pass
    return "", since


def _dated_lines(log: str, since: datetime):
    stamp = None
    for line in log.splitlines():
        if match := _DATED.match(line):
            stamp = datetime.fromisoformat(match[1]).replace(tzinfo=BEIJING)
        if stamp and stamp >= since:
            yield stamp, line


def _clock_lines(log: str, modified: datetime, since: datetime):
    """交错的时分秒日志从末尾倒推日期，跨零点时回退一天。"""
    date = modified.date()
    last = None
    rows = []
    for line in reversed(log.splitlines()):
        if not (match := _STAMP.match(line)):
            continue
        clock = time.fromisoformat(match[1])
        seconds = clock.hour * 3600 + clock.minute * 60 + clock.second
        if last is not None and seconds - last > 12 * 3600:
            date -= timedelta(days=1)
        last = seconds
        stamp = datetime.combine(date, clock, BEIJING)
        if stamp < since:
            break
        rows.append((stamp, line))
    return list(reversed(rows))


def _rolling_logs(active: Path, since: datetime, now: datetime, date_name, *, dated=False):
    date = since.date()
    rows = []
    while date <= now.date():
        rotated = active.with_name(date_name(date.isoformat()))
        log, modified = _read(rotated, since)
        midnight = datetime.combine(date, modified.time(), BEIJING)
        rows.extend(_dated_lines(log, since) if dated else _clock_lines(log, midnight, since))
        date += timedelta(days=1)
    log, modified = _read(active, since)
    rows.extend(_dated_lines(log, since) if dated else _clock_lines(log, modified, since))
    # 文件刚滚动时可能重复读到同一批行。按时间稳定排序，保留同秒的原始顺序。
    return sorted(dict.fromkeys(rows), key=lambda row: row[0])


def _chain_runs(rows) -> dict[str, Run]:
    runs: dict[str, Run] = {}
    for stamp, line in rows:
        if not (match := _CHAIN_EVENT.search(line)) or match[2].strip() not in _CHAIN_GAME:
            continue
        game = _CHAIN_GAME[match[2].strip()]
        kind = match[1]
        if kind == "正在运行":
            runs[game] = Run(started=stamp)
            continue
        run = runs.setdefault(game, Run())
        if run.ended is None:
            run.ended = stamp
            run.state = {"运行结束": "脚本结束", "游戏或脚本被关闭": "脚本已退出",
                         "取消运行": "已取消", "运行超时": "脚本超时"}[kind]
    return runs


def _iso(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.astimezone(BEIJING) if stamp.tzinfo else stamp.replace(tzinfo=BEIJING)
    except (ValueError, TypeError):
        return None


def _hsr(folder: Path, since: datetime, fallback: Run) -> Daily:
    result = Daily(run=fallback)
    score = None
    dungeons = Counter()
    latest_run = None
    try:
        files = sorted({path.with_suffix(".log") for path in folder.iterdir()
                        if path.suffix in {".log", ".json"}})
    except OSError:
        files = []
    for path in files:
        log, _ = _read(path, since)
        meta, _ = _read(path.with_suffix(".json"), since)
        if not log and not meta:
            continue
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
        if isinstance(meta, dict):
            started, ended = _iso(meta.get("started_at")), _iso(meta.get("ended_at"))
            if started and (started >= since or (ended and ended >= since)):
                status = str(meta.get("status", "")).lower()
                state = {"success": "脚本完成", "completed": "脚本完成", "failed": "异常退出",
                         "cancelled": "已取消", "canceled": "已取消", "aborted": "已中止"}.get(status, "脚本结束")
                if latest_run is None or started >= latest_run.started:
                    latest_run = Run(started, ended, state if ended else "")

        name, rounds, group, completed = "", 0, 0, 0
        for stamp, line in _dated_lines(log, since):
            if match := re.search(r"(?:当前累计分数|当前分数)[：:]\s*(\d+)\s*/\s*500", line):
                score = max(score or 0, int(match[1]))
                if score >= 500 and result.completed is None:
                    result.completed = stamp
            if "每日实训已完成" in line:
                score = max(score or 0, 500)
                result.completed = result.completed or stamp
            if match := re.search(r"开始刷(.+?)[，,]总计\s*(\d+)轮[，,]每轮包含\s*(\d+)次", line):
                if name and completed:
                    dungeons[name] += completed * group
                name, rounds, group, completed = match[1].strip(), int(match[2]), int(match[3]), 0
            elif name and (match := re.search(r"第\s*(\d+)\s*次副本完成", line)):
                completed = max(completed, min(rounds, int(match[1])))
            elif name and "副本任务完成" in line:
                completed = rounds
        if name and completed:
            dungeons[name] += completed * group

    if latest_run and (fallback.started is None or (
            latest_run.started >= fallback.started - timedelta(seconds=60)
            and (latest_run.ended is None or latest_run.ended >= fallback.started))):
        result.run = latest_run
    if score is not None:
        result.activity = f"每日实训 {score}/500"
        result.activity_full = score >= 500
    if dungeons:
        result.stamina = "、".join(f"{name} ×{n}" for name, n in dungeons.items())
    return result


def _zzz(rows, fallback: Run) -> Daily:
    result = Daily(run=fallback)
    dungeons = Counter()
    used = 0
    before = last = None
    saw_fight = False
    direct = Run()
    for stamp, line in rows:
        if "发现" in line and "默认组应用" in line:
            direct = Run(started=stamp)
            before = last = None
            saw_fight = False
        if "指令[ 活跃度奖励 ]" in line:
            if "返回状态 活跃度已满" in line:
                result.activity = "活跃度已满"
                result.activity_full = True
                result.completed = result.completed or stamp
            elif "返回状态 活跃度未满" in line and result.activity_full is not True:
                result.activity = "活跃度未满"
                result.activity_full = False
        if match := re.search(r"指令\[\s*((?:区域巡防|实战模拟室|专业挑战室)\s+.*?)\s*\] 节点 战斗结束.*战斗结果-(?:再来一次|完成)", line):
            dungeons[match[1]] += 1
            saw_fight = True
        if "[charge_plan_app.py" in line and (match := re.search(r"剩余电量\s+(\d+)", line)):
            last = int(match[1])
            if before is None:
                before = last
        if "指令[ 体力刷本 ] 执行成功" in line and saw_fight and before is not None and last is not None:
            used += max(0, before - last)
            before, saw_fight = None, False
        if "指令[ 一条龙 ] 执行成功 返回状态 全部结束" in line:
            direct.ended, direct.state = stamp, "脚本完成"
    if dungeons:
        result.stamina = "、".join(f"{name} ×{n}" for name, n in dungeons.items())
        if used:
            result.stamina += f" · 电量 −{used}"
    result.run = _merge_run(fallback, direct)
    return result


def _ww(rows, fallback: Run) -> Daily:
    result = Daily(run=fallback)
    direct = Run()
    dungeons = Counter()
    target = ""
    last = None
    spent = pending = unit = 0
    for stamp, line in rows:
        if "ok:ok-script init" in line:
            direct = Run(started=stamp)
            target, last, pending = "", None, 0
        if "DailyTask:每日任务已完成" in line:
            result.activity = "活跃度奖励流程完成"
            result.completed = result.completed or stamp
        if "Successfully Executed Task, Exiting Game and App" in line:
            direct.ended, direct.state = stamp, "脚本完成"
        if match := re.search(r"(?:TacetTask|ForgeryTask|SimulationTask):info_set current_stamina\s+(\d+)|BaseWWTask:current stamina: (-?\d+) (?:must_use completed|not enough to continue)", line):
            meter = int(match[1] or match[2])
            if pending and meter != last:
                if last is not None and 0 <= meter <= last - pending:
                    dungeons[target] += 1
                    spent += pending
                pending = 0
            last = meter if meter >= 0 else None
        if match := re.search(r"info_set (Teleport to Tacet Suppression|Teleport to Forgery Challenge|Target Simulation Challenge)\s+(\d+)", line):
            category, unit = {"Teleport to Tacet Suppression": ("无音区", 60),
                              "Teleport to Forgery Challenge": ("凝素领域", 40),
                              "Target Simulation Challenge": ("模拟训练", 40)}[match[1]]
            index = int(match[2]) + (match[1] != "Target Simulation Challenge")
            target, pending = f"{category} · 列表第 {index} 项", 0
        if target and "BaseWWTask:" in line:
            if "当前体力大于等于双倍" in line or "使用双倍" in line:
                pending = unit * 2
            elif "使用单倍体力" in line:
                pending = unit
    if dungeons:
        result.stamina = "、".join(f"{name} ×{n}" for name, n in dungeons.items())
        if spent:
            result.stamina += f" · 波片 −{spent}"
    if result.completed:
        result.activity_full = spent >= 180
        if not result.activity_full:
            result.reminder_detail = "流程完成 · 未确认消耗至少 180 波片"
    result.run = _merge_run(fallback, direct)
    return result


def _merge_run(chain: Run, direct: Run) -> Run:
    # 子脚本可手动独立启动。临近的两条启动记录合并为一轮。
    if chain.started is None or (direct.started and direct.started > chain.started + timedelta(seconds=60)):
        return direct if direct.started or direct.ended else chain
    if direct.ended and direct.ended >= chain.started and chain.state not in {"脚本超时", "已取消"}:
        return Run(chain.started, chain.ended or direct.ended, direct.state)
    return chain


def read_today(root: str = "", now: datetime | None = None, *,
               folders: dict[str, str] | None = None) -> tuple[datetime, dict[str, Daily]]:
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    since = daily_start(now)
    locations = locate_logs(root, folders)
    chain = locations["chain"].folder / "script_chainer_runner.log"
    runs_root = locations["sr"].folder
    zzz = locations["zzz"].folder / "log.txt"
    ww = locations["ww"].folder / "ok-script.log"
    runs = _chain_runs(_rolling_logs(chain, since, now, lambda date: f"{chain.name}.{date}"))
    result = {
        "sr": _hsr(runs_root, since, runs.get("sr", Run())),
        "zzz": _zzz(_rolling_logs(zzz, since, now, lambda date: f"{zzz.name}.{date}"), runs.get("zzz", Run())),
        "ww": _ww(_rolling_logs(ww, since, now, lambda date: f"ok-script.{date}.log", dated=True), runs.get("ww", Run())),
    }
    for game in DAILY_GAMES:
        if not locations[game].found and game not in runs:
            result[game].activity = "找不到日志"
    return now, result
