# -*- coding: utf-8 -*-
"""活动日历上方的日常摘要。"""
from datetime import datetime
from functools import partial

from PySide6 import QtCore, QtWidgets

from ...core import bg
from ...services.game_calendar import BEIJING
from ...services.game_daily import DAILY_GAMES, Daily, daily_start, log_settings, read_today
from ..theme import G, W
from ..widgets import Card, IconButton, Label, hbox, vbox


def _runtime(daily: Daily) -> str:
    run = daily.run
    parts = []
    if daily.completed:
        parts.append(f"日常 {daily.completed:%H:%M}")
    if run.ended:
        parts.append(f"{run.state} {run.ended:%H:%M}")
        if run.started and run.started <= run.ended:
            seconds = int((run.ended - run.started).total_seconds())
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            parts.append(f"{hours}时{minutes}分" if hours else f"{minutes}分{seconds:02d}秒")
    elif run.started:
        parts.append(f"已启动 {run.started:%H:%M} · 未见结束")
    return " · ".join(parts)


class DailyPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = False
        self._generation = 0
        self._day = None
        self._timer = QtCore.QTimer(self, interval=30_000, timeout=self.refresh)
        self._stamp = Label("等待读取", 11, level=3)
        reload_ = IconButton(G.REFRESH, 26, 11, "刷新日常日志")
        reload_.clicked.connect(self.refresh)
        header = hbox(Label("今日日常", 15, W.DemiBold), None, self._stamp, reload_, spacing=4, margins=(2, 0, 2, 0))

        self._rows = {}
        card = Card(radius=14)
        body = QtWidgets.QVBoxLayout(card)
        body.setSpacing(4)
        body.setContentsMargins(10, 5, 10, 5)
        for game, title in DAILY_GAMES.items():
            name = Label(title, 13, W.DemiBold)
            name.setFixedWidth(56)
            activity = Label("等待日志", 13, W.DemiBold)
            timing = Label("", 11, level=2)
            stamina = Label("", 11, level=2)
            timing.setMinimumWidth(215)
            body.addLayout(hbox(name, (activity, 1), timing, spacing=4))
            body.addLayout(hbox(60, (stamina, 1), spacing=0))
            self._rows[game] = activity, stamina, timing
        self.setLayout(vbox(header, card, spacing=4))

    def start(self):
        self.refresh()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def reload_sources(self):
        self._generation += 1
        self._pending = False
        self._day = None

    def refresh(self):
        if self._pending:
            return
        day = daily_start(datetime.now(BEIJING)).date()
        if self._day != day:
            self._stamp.setText("正在读日志…")
            for activity, stamina, timing in self._rows.values():
                activity.setText("等待日志")
                stamina.setText("")
                timing.setText("")
                stamina.setToolTip("")
                timing.setToolTip("")
        self._pending = True
        root, folders = log_settings()
        generation = self._generation
        bg.run_bg(partial(read_today, root, folders=folders),
                  on_done=lambda data: self._finish(generation, data),
                  on_error=lambda error: self._error(generation, error))

    def _finish(self, generation, data):
        if generation != self._generation:
            return
        self._pending = False
        now, games = data
        if daily_start(now) != daily_start(datetime.now(BEIJING)):
            if self._timer.isActive():
                self.refresh()
            return
        self._day = daily_start(now).date()
        self._stamp.setText(f"{self._day.month}/{self._day.day} · 日志 {now:%H:%M:%S}")
        self._stamp.setToolTip("北京时间 04:00 换日。页面打开时每 30 秒检查一次日志。")
        for game, result in games.items():
            activity, stamina, timing = self._rows[game]
            activity.setText(result.activity)
            stamina.setText(f"体力 · {result.stamina}")
            stamina.setToolTip(result.stamina)
            runtime = _runtime(result)
            timing.setText(runtime)
            timing.setToolTip(runtime)

    def _error(self, generation, _error):
        if generation != self._generation:
            return
        self._pending = False
        self._stamp.setText("日常日志读取失败")
