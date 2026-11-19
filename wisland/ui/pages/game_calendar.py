# -*- coding: utf-8 -*-
"""二游活动的横向日历。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html import escape
from itertools import count
from time import monotonic

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import bg
from ...core.config import cfg
from ...services.game_calendar import BEIJING, GAMES, Activity, GameCalendar, fetch_calendar, selected_games
from ..theme import G, W, theme, ui_font
from ..widgets import Card, IconButton, Label, ScrollArea, hbox, painter, vbox
from .base import Page
from .game_daily import DailyPanel

Qt = QtCore.Qt
DAYS = 14
AXIS_PAD = 10
ROW_H = 25
SCROLL_W = 6
DAY = timedelta(days=1)
DEADLINE_WINDOW = timedelta(hours=72)
MOONLIT_SHORE = ("#90C1E0", "#ABAFE7", "#74CDBE", "#B4BEDB", "#7BB0DD", "#BFA9DE", "#ACD3BA", "#A1CED6")


def _month_day(dt: datetime) -> str:
    return f"{dt.month}/{dt.day}"


def _shore_colors():
    """色板用完后在原有色相内延伸，避免同一页有重复色值。"""
    seen = set()
    for band in count():
        for base in MOONLIT_SHORE:
            color = QtGui.QColor(base)
            if band:
                hue, saturation, lightness, _ = color.getHsl()
                shift = ((band + 1) // 2) * (9 if band % 2 == 0 else -9)
                color.setHsl(hue, 60 + (saturation - 60 + band * 17) % 96,
                             150 + (lightness - 150 + shift) % 66)
            name = color.name()
            if name not in seen:
                seen.add(name)
                yield name


@dataclass(frozen=True)
class _Row:
    title: str
    note: str = ""
    activity: Activity | None = None
    game: str = ""
    collapsed: bool = False
    tone: str = ""


class _Timeline(QtWidgets.QWidget):
    game_clicked = QtCore.Signal(str)

    def __init__(self, ruler=False):
        super().__init__()
        self.ruler = ruler
        self.rows: list[_Row] = []
        self.deadlines: list[tuple[str, Activity]] = []
        self.now = datetime.now(BEIJING)
        self.start = self.now
        self._hovered_game = ""
        self._pressed_game = ""
        self.setMouseTracking(not ruler)
        self.setFixedHeight(36 if ruler else 0)
        theme.changed.connect(self.update)

    def set_window(self, start: datetime, now: datetime, rows: list[_Row],
                   deadlines: list[tuple[str, Activity]] | None = None):
        self.start, self.now, self.rows = start, now, rows
        self.deadlines = deadlines or []
        if not self.ruler:
            self.setFixedHeight(len(rows) * ROW_H)
        self.update()

    def _x(self, days: float) -> float:
        return AXIS_PAD + days * (self.width() - 2 * AXIS_PAD) / DAYS

    def paintEvent(self, event):
        p = painter(self)
        today = (self.now.date() - self.start.date()).days
        if 0 <= today < DAYS:
            shade = theme.accent
            shade.setAlphaF(0.12)
            p.fillRect(QtCore.QRectF(self._x(today), 0, self._x(1) - self._x(0), self.height()), shade)
        p.setPen(theme.text(0.09))
        for d in range(DAYS + 1):
            p.drawLine(QtCore.QLineF(self._x(d), 0, self._x(d), self.height()))

        if self.ruler:
            self._paint_ruler(p, today)
            return
        first = max(0, event.rect().top() // ROW_H)
        last = min(len(self.rows), event.rect().bottom() // ROW_H + 1)
        for index in range(first, last):
            self._paint_row(p, self.rows[index], index * ROW_H)

    def _paint_ruler(self, p, today):
        p.setFont(ui_font(11, W.Medium))
        label_font = p.font()
        width = self._x(1) - self._x(0)
        for i in range(DAYS):
            dt = self.start + i * DAY
            p.setPen(theme.accent if i == today else theme.text2())
            p.drawText(QtCore.QRectF(self._x(i), 1, width, 17), Qt.AlignmentFlag.AlignCenter, _month_day(dt))
            p.setPen(theme.accent if i == today else theme.text3())
            weekday = "今天" if i == today else "一二三四五六日"[dt.weekday()]
            label_rect = QtCore.QRectF(self._x(i), 18, width, 15)
            if i != today or not self.deadlines:
                p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, weekday)
                continue

            value = str(len(self.deadlines)) if len(self.deadlines) <= 99 else "99+"
            badge_font = ui_font(10, W.DemiBold, num=True)
            metrics = QtGui.QFontMetricsF(badge_font)
            badge_width = max(15, metrics.horizontalAdvance(value) + 6)
            text_width = p.fontMetrics().horizontalAdvance(weekday) + 1
            left = label_rect.center().x() - (text_width + 3 + badge_width) / 2
            p.drawText(QtCore.QRectF(left, 18, text_width, 15), Qt.AlignmentFlag.AlignCenter, weekday)
            badge = QtCore.QRectF(left + text_width + 3, 18, badge_width, 15)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor("#FFD686" if theme.dark else "#A45300"))
            p.drawRoundedRect(badge, 7.5, 7.5)
            p.setPen(QtGui.QColor("#3B2506" if theme.dark else "#FFFFFF"))
            p.setFont(badge_font)
            p.drawText(badge.center() - metrics.tightBoundingRect(value).center(), value)
            p.setFont(label_font)

    def _paint_row(self, p, row: _Row, y: int):
        if row.activity is None:
            self._paint_heading(p, row, y)
            return

        item = row.activity
        tone = QtGui.QColor(row.tone)
        left, right = self._x(0), self._x(DAYS)
        start_x = self._x(max(0, (item.start - self.start) / DAY))
        end_x = self._x(min(DAYS, (item.end - self.start) / DAY))
        width = max(5.0, end_x - start_x)
        bar = QtCore.QRectF(min(start_x, right - width), y + 3, width, ROW_H - 6)
        ongoing = item.start <= self.now <= item.end
        upcoming = item.start > self.now
        fill = QtGui.QColor(tone)
        if not ongoing:
            fill.setAlphaF(0.22 if upcoming else 0.13)
        if upcoming:
            outline = tone if theme.dark else tone.darker(145)
            p.setPen(QtGui.QPen(outline, 1))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(bar, min(5.0, bar.width() / 2), 5)

        p.setFont(ui_font(12, W.Medium))
        metrics = p.fontMetrics()
        label = bar.adjusted(7, 0, -7, 0)
        align = Qt.AlignmentFlag.AlignLeft
        inline = label.width() >= min(52, metrics.horizontalAdvance(row.title))
        if not inline:
            before, after = bar.left() - left, right - bar.right()
            if after >= before:
                label = QtCore.QRectF(bar.right() + 6, y, after - 6, ROW_H)
            else:
                label = QtCore.QRectF(left, y, before - 6, ROW_H)
                align = Qt.AlignmentFlag.AlignRight
        if label.width() > 0:
            text_color = theme.text2() if item.end < self.now else theme.text()
            p.setPen(QtGui.QColor("#1d2230") if ongoing and inline else text_color)
            text = metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, int(label.width()))
            p.drawText(label, Qt.AlignmentFlag.AlignVCenter | align, text)

    def _paint_heading(self, p, row: _Row, y: int):
        hovered = bool(row.game and row.game == self._hovered_game)
        rect = QtCore.QRectF(0, y, self.width(), ROW_H)
        p.fillRect(rect, theme.card())
        if hovered:
            p.fillRect(rect, theme.hover())
        x = AXIS_PAD
        if row.game:
            pen = QtGui.QPen(theme.text2(), 1.25)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            mid = y + ROW_H / 2
            points = [(3, -4), (7, 0), (3, 4)] if row.collapsed else [(1, -2), (5, 2), (9, -2)]
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x + dx, mid + dy) for dx, dy in points]))
            x += 18
        p.setFont(ui_font(12, W.DemiBold))
        p.setPen(theme.text())
        title_width = p.fontMetrics().horizontalAdvance(row.title)
        p.drawText(QtCore.QRectF(x, y, title_width + 2, ROW_H), Qt.AlignmentFlag.AlignVCenter, row.title)
        note_x = x + title_width + 12
        p.setFont(ui_font(11))
        p.setPen(theme.text2())
        note_width = max(0, self.width() - AXIS_PAD - note_x)
        note = p.fontMetrics().elidedText(row.note, Qt.TextElideMode.ElideRight, note_width)
        p.drawText(QtCore.QRectF(note_x, y, note_width, ROW_H), Qt.AlignmentFlag.AlignVCenter, note)

    def _game_at(self, pos: QtCore.QPoint) -> str:
        if self.rect().contains(pos):
            i = pos.y() // ROW_H
            if i < len(self.rows) and self.rows[i].activity is None:
                return self.rows[i].game
        return ""

    def mouseMoveEvent(self, event):
        game = self._game_at(event.position().toPoint())
        if game != self._hovered_game:
            self._hovered_game = game
            self.setCursor(Qt.CursorShape.PointingHandCursor if game else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_game = ""
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_game = self._game_at(event.position().toPoint())
            if self._pressed_game:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_game:
            game, self._pressed_game = self._pressed_game, ""
            if game == self._game_at(event.position().toPoint()):
                self.game_clicked.emit(game)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def event(self, event):
        if self.ruler and self.deadlines and event.type() == QtCore.QEvent.Type.ToolTip:
            today = (self.now.date() - self.start.date()).days
            if 0 <= today < DAYS:
                width = self._x(1) - self._x(0)
                cell = QtCore.QRectF(self._x(today), 0, width, self.height()).toAlignedRect()
                if cell.contains(event.pos()):
                    tip = [f"<b>{len(self.deadlines)} 项活动将在 72 小时内结束</b>"]
                    tip += [f"{escape(GAMES[game])} · {escape(item.name)}　{item.end:%m/%d %H:%M}"
                            for game, item in self.deadlines[:10]]
                    if len(self.deadlines) > 10:
                        tip.append(f"另有 {len(self.deadlines) - 10} 项")
                    QtWidgets.QToolTip.showText(event.globalPos(), "<br>".join(tip), self, cell)
                    return True
        if not self.ruler and event.type() == QtCore.QEvent.Type.ToolTip:
            i = event.pos().y() // ROW_H
            if 0 <= i < len(self.rows) and (item := self.rows[i].activity):
                state = "已结束" if item.end < self.now else "未开始" if item.start > self.now else "进行中"
                desc = escape(" ".join(item.description.split())[:380])
                tip = (f"<b>{escape(item.name)}</b><br>{state}"
                       f"{(' · ' + escape(item.kind)) if item.kind else ''}<br>"
                       f"{item.start:%m/%d %H:%M} – {item.end:%m/%d %H:%M}（北京时间）")
                if desc:
                    tip += f"<br><p style='white-space:normal'>{desc}</p>"
                QtWidgets.QToolTip.showText(event.globalPos(), tip, self, QtCore.QRect(0, i * ROW_H, self.width(), ROW_H))
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


class GameCalendarPage(Page):
    key, glyph, title, height = "calendar", G.CALENDAR, "活动日历", 450
    REFRESH_SECONDS = 1800
    deadlines_changed = QtCore.Signal(int)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._games = selected_games()
        self._data: dict[str, GameCalendar] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._requested: dict[str, float] = {}
        self._collapsed: set[str] = set()
        self._monitoring = False
        self._week = 0
        self._timer = QtCore.QTimer(self, interval=60_000, timeout=self._refresh)

        prev = IconButton("\uE76B", 26, 11, "上一周")
        prev.clicked.connect(lambda: self._shift(-1))
        today = IconButton(G.CALENDAR, 28, 13, "回到今天")
        today.clicked.connect(lambda: self._shift())
        next_ = IconButton("\uE76C", 26, 11, "下一周")
        next_.clicked.connect(lambda: self._shift(1))
        self._reload = IconButton(G.REFRESH, 28, 12, "刷新活动")
        self._reload.clicked.connect(lambda: self._refresh(force=True))
        self._range = Label("", 12, W.Medium, level=2)
        self._range.setToolTip("北京时间")
        header = hbox(Label("活动日历", 15, W.DemiBold), self._range, None, prev, today, next_, self._reload,
                      spacing=4, margins=(2, 0, 2, 0))

        self._ruler = _Timeline(ruler=True)
        self._timeline = _Timeline()
        self._timeline.game_clicked.connect(self._toggle_game)
        self._scroll = ScrollArea()
        self._scroll.verticalScrollBar().setFixedWidth(SCROLL_W)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.inner.setLayout(vbox(self._timeline, None, spacing=0))
        card = Card(radius=14)
        card.setLayout(vbox(hbox((self._ruler, 1), SCROLL_W, spacing=0), (self._scroll, 1), spacing=0))
        self._daily = DailyPanel(self)
        self._daily_enabled = bool(cfg.get("game_daily.enabled", True))
        self._daily.setVisible(self._daily_enabled)
        self.setLayout(vbox(self._daily, header, (card, 1), spacing=8))
        self._render()

    def on_show(self):
        super().on_show()
        self._games = selected_games()
        self._refresh()
        if self._daily_enabled:
            self._daily.start()

    def on_hide(self):
        self._daily.stop()
        super().on_hide()

    def set_monitoring(self, on: bool):
        if self._monitoring == on:
            return
        self._monitoring = on
        if on:
            self._refresh()
            self._timer.start()
        else:
            self._timer.stop()
            self.deadlines_changed.emit(0)

    def set_games(self, games: list[str]):
        self._games = games
        if self.active or self._monitoring:
            self._refresh()

    def reload_daily_logs(self):
        self._daily_enabled = bool(cfg.get("game_daily.enabled", True))
        self._daily.setVisible(self._daily_enabled)
        self._daily.stop()
        self._daily.reload_sources()
        if self.active and self._daily_enabled:
            self._daily.start()
        if self.active and self.island:
            self.island.page_size_changed()

    def preferred_height(self) -> int:
        return self.height if self._daily_enabled else 382

    def _refresh(self, force=False):
        now = monotonic()
        for game in self._games:
            age = now - self._requested.get(game, float("-inf"))
            interval = 120 if game in self._failed else self.REFRESH_SECONDS
            if game in self._pending or (not force and age < interval):
                continue
            self._requested[game] = now
            self._pending.add(game)
            bg.run_bg(fetch_calendar, game, on_done=lambda result, k=game: self._finish(k, result),
                      on_error=lambda _error, k=game: self._finish(k, None))
        self._update_activity_view()

    def _finish(self, game: str, data: GameCalendar | None):
        self._pending.discard(game)
        if data is None:
            self._failed.add(game)
        else:
            self._failed.discard(game)
            self._data[game] = data
        if game in self._games:
            self._update_activity_view()

    def _upcoming_deadlines(self, now: datetime) -> list[tuple[str, Activity]]:
        cutoff = now + DEADLINE_WINDOW
        return sorted(((game, item) for game in self._games if game in self._data
                       for item in self._data[game].activities if now < item.end <= cutoff),
                      key=lambda entry: entry[1].end)

    def _update_activity_view(self):
        if self.active:
            self._render()
        elif self._monitoring:
            self.deadlines_changed.emit(len(self._upcoming_deadlines(datetime.now(BEIJING))))

    def _shift(self, delta: int = 0):
        self._week = self._week + delta if delta else 0
        self._scroll.verticalScrollBar().setValue(0)
        self._render()

    def _toggle_game(self, game: str):
        if game in self._collapsed:
            self._collapsed.remove(game)
        else:
            self._collapsed.add(game)
        self._render()

    def _render(self):
        now = datetime.now(BEIJING)
        start = datetime.combine(now.date(), time.min, BEIJING) + (self._week * 7 - 2) * DAY
        end = start + DAYS * DAY
        self._range.setText(f"  {_month_day(start)} – {_month_day(end - DAY)}")
        self._reload.setEnabled(any(game not in self._pending for game in self._games))
        rows: list[_Row] = []
        tones = _shore_colors()
        # 固定按档期顺序配色，折叠、翻周、调序都不会改变已加载活动的色值。
        colors = {(game, item): next(tones) for game in GAMES if game in self._data
                  for item in sorted(self._data[game].activities, key=lambda item: (item.end, item.name, item.start))}
        deadlines = self._upcoming_deadlines(now)
        for game in self._games:
            collapsed = game in self._collapsed
            data = self._data.get(game)
            if data is None:
                note = "获取失败 · 可刷新重试" if game in self._failed and game not in self._pending else "正在获取…"
                rows.append(_Row(GAMES[game], note, game=game, collapsed=collapsed))
                continue
            items = [item for item in data.activities if item.end >= start and item.start < end]
            items.sort(key=lambda item: (item.end < now, item.start > now,
                                         item.start if item.start > now else item.end, item.name))
            note = f"{data.version} 版本" if data.version else ""
            if not items:
                note = " · ".join(filter(None, (note, "这段时间暂无活动")))
            elif collapsed:
                note = " · ".join(filter(None, (note, f"{len(items)} 项活动")))
            if game in self._failed:
                note = " · ".join(filter(None, (note, "刷新失败 · 上次数据")))
            rows.append(_Row(GAMES[game], note, game=game, collapsed=collapsed))
            if not collapsed:
                rows.extend(_Row(item.name, activity=item, game=game, tone=colors[game, item]) for item in items)
        if not rows:
            rows.append(_Row("未选择游戏", "在「设置 → 活动日历」里选择"))
        self._ruler.set_window(start, now, [], deadlines)
        self._timeline.set_window(start, now, rows)
        if self._monitoring:
            self.deadlines_changed.emit(len(deadlines))
