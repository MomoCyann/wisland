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


def _activity_key(game: str, item: Activity) -> str:
    return f"{game}|{item.start.isoformat()}|{item.end.isoformat()}|{item.name}"


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
    acknowledged: bool = False


class _Timeline(QtWidgets.QWidget):
    game_clicked = QtCore.Signal(str)
    activity_clicked = QtCore.Signal(str, object)
    game_reordered = QtCore.Signal(str, str)
    dragging_changed = QtCore.Signal(bool)

    def __init__(self, ruler=False, scroll_area=None):
        super().__init__()
        self.ruler = ruler
        self._scroll_area = scroll_area
        self.rows: list[_Row] = []
        self._headings: list[int] = []
        self.deadlines: list[tuple[str, Activity]] = []
        self.now = datetime.now(BEIJING)
        self.start = self.now
        self._hovered_game = ""
        self._pressed_row: _Row | None = None
        self._press_pos = QtCore.QPoint()
        self._drag_game = ""
        self._drag_pos = QtCore.QPoint()
        self._drop_row: int | None = None
        self._drag_timer = QtCore.QTimer(self, interval=30, timeout=self._scroll_drag)
        self.setMouseTracking(not ruler)
        self.setFixedHeight(36 if ruler else 0)
        theme.changed.connect(self.update)

    def set_window(self, start: datetime, now: datetime, rows: list[_Row],
                   deadlines: list[tuple[str, Activity]] | None = None):
        self.start, self.now, self.rows = start, now, rows
        self._headings = [i for i, row in enumerate(rows) if row.game and row.activity is None]
        self.deadlines = deadlines or []
        if not self.ruler:
            self.setFixedHeight(len(rows) * ROW_H)
            if self._drag_game:
                self._update_drop(self._drag_pos)
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
        if self._drop_row is not None:
            y = min(self._drop_row * ROW_H, self.height() - 2)
            p.setPen(QtGui.QPen(theme.accent, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(AXIS_PAD, max(1, y), self.width() - AXIS_PAD, max(1, y))

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
        bar = self._bar_rect(item, y)
        ongoing = item.start <= self.now <= item.end
        upcoming = item.start > self.now
        fill = QtGui.QColor(tone)
        if row.acknowledged:
            fill.setAlphaF(0.28 if ongoing else 0.12)
        elif not ongoing:
            fill.setAlphaF(0.22 if upcoming else 0.13)
        if upcoming and not row.acknowledged:
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
            text_color = theme.text2() if item.end < self.now or row.acknowledged else theme.text()
            p.setPen(QtGui.QColor("#1d2230") if ongoing and inline and not row.acknowledged else text_color)
            text = metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, int(label.width()))
            p.drawText(label, Qt.AlignmentFlag.AlignVCenter | align, text)

    def _paint_heading(self, p, row: _Row, y: int):
        hovered = bool(row.game and row.game == self._hovered_game)
        rect = QtCore.QRectF(0, y, self.width(), ROW_H)
        p.fillRect(rect, theme.card())
        if hovered or (self._drag_game and row.game == self._drag_game):
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
            if len(self._headings) > 1:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.text3())
                for dx in (0, 4):
                    for dy in (-4, 0, 4):
                        p.drawEllipse(QtCore.QPointF(self.width() - AXIS_PAD - 9 + dx, mid + dy), 1.1, 1.1)
        p.setFont(ui_font(12, W.DemiBold))
        p.setPen(theme.text())
        title_width = p.fontMetrics().horizontalAdvance(row.title)
        p.drawText(QtCore.QRectF(x, y, title_width + 2, ROW_H), Qt.AlignmentFlag.AlignVCenter, row.title)
        note_x = x + title_width + 12
        p.setFont(ui_font(11))
        p.setPen(theme.text2())
        note_width = max(0, self.width() - AXIS_PAD - 18 - note_x)
        note = p.fontMetrics().elidedText(row.note, Qt.TextElideMode.ElideRight, note_width)
        p.drawText(QtCore.QRectF(note_x, y, note_width, ROW_H), Qt.AlignmentFlag.AlignVCenter, note)

    def _bar_rect(self, item: Activity, y: int) -> QtCore.QRectF:
        start_x = self._x(max(0, (item.start - self.start) / DAY))
        end_x = self._x(min(DAYS, (item.end - self.start) / DAY))
        width = max(5.0, end_x - start_x)
        return QtCore.QRectF(min(start_x, self._x(DAYS) - width), y + 3, width, ROW_H - 6)

    def _row_at(self, pos: QtCore.QPoint) -> _Row | None:
        if self.rect().contains(pos):
            i = pos.y() // ROW_H
            if i < len(self.rows):
                row = self.rows[i]
                if row.game and (row.activity is None or self._bar_rect(row.activity, i * ROW_H).contains(QtCore.QPointF(pos))):
                    return row
        return None

    def _update_drop(self, pos: QtCore.QPoint):
        self._drag_pos = pos
        viewport = self._scroll_area.viewport()
        self._drop_row = None
        if viewport.rect().contains(viewport.mapFromGlobal(pos)):
            y = self.mapFromGlobal(pos).y()
            self._drop_row = next((i for i in self._headings if y < (i + 0.5) * ROW_H), len(self.rows))
        self.update()

    def _scroll_drag(self):
        viewport = self._scroll_area.viewport()
        pos = viewport.mapFromGlobal(self._drag_pos)
        if not viewport.rect().contains(pos):
            return
        margin = min(24, viewport.height() // 3)
        distance = min(0, pos.y() - margin) + max(0, pos.y() - (viewport.height() - margin))
        bar = self._scroll_area.verticalScrollBar()
        old = bar.value()
        bar.setValue(old + distance // 2)
        if bar.value() != old:
            self._update_drop(self._drag_pos)

    def cancel_drag(self):
        self._pressed_row = None
        if self._drag_game:
            self._drag_game = ""
            self._drop_row = None
            self._drag_timer.stop()
            self.unsetCursor()
            self.update()
            self.dragging_changed.emit(False)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        left_down = bool(event.buttons() & Qt.MouseButton.LeftButton)
        if self._drag_game and not left_down:
            self.cancel_drag()
        if (not self._drag_game and self._pressed_row and self._pressed_row.activity is None
                and self._scroll_area and left_down
                and abs(pos.y() - self._press_pos.y()) >= QtWidgets.QApplication.startDragDistance()
                and len(self._headings) > 1):
            self._drag_game = self._pressed_row.game
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            QtWidgets.QToolTip.hideText()
            self.dragging_changed.emit(True)
            self._drag_timer.start()
        if self._drag_game:
            self._update_drop(event.globalPosition().toPoint())
            event.accept()
            return
        row = self._row_at(pos)
        game = row.game if row and row.activity is None else ""
        self.setCursor(Qt.CursorShape.PointingHandCursor if row else Qt.CursorShape.ArrowCursor)
        if game != self._hovered_game:
            self._hovered_game = game
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_game = ""
        if not self._drag_game:
            self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._pressed_row = self._row_at(self._press_pos)
            if self._pressed_row:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_game:
            self._update_drop(event.globalPosition().toPoint())
            game, drop = self._drag_game, self._drop_row
            before = self.rows[drop].game if drop is not None and drop < len(self.rows) else ""
            self.cancel_drag()
            if drop is not None:
                self.game_reordered.emit(game, before)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_row:
            row, self._pressed_row = self._pressed_row, None
            if row == self._row_at(event.position().toPoint()):
                if row.activity is None:
                    self.game_clicked.emit(row.game)
                else:
                    self.activity_clicked.emit(row.game, row.activity)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.UngrabMouse):
            self.cancel_drag()
        if self._drag_game and event.type() == QtCore.QEvent.Type.ToolTip:
            return True
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
                row = self.rows[i]
                state = "已结束" if item.end < self.now else "未开始" if item.start > self.now else "进行中"
                desc = escape(" ".join(item.description.split())[:380])
                tip = (f"<b>{escape(item.name)}</b><br>{state}"
                       f"{(' · ' + escape(item.kind)) if item.kind else ''}<br>"
                       f"{item.start:%m/%d %H:%M} – {item.end:%m/%d %H:%M}（北京时间）")
                tip += "<br>已确认 · 点击色条恢复提醒" if row.acknowledged else "<br>点击色条确认活动"
                if desc:
                    tip += f"<br><p style='white-space:normal'>{desc}</p>"
                QtWidgets.QToolTip.showText(event.globalPos(), tip, self, QtCore.QRect(0, i * ROW_H, self.width(), ROW_H))
            elif i in self._headings and len(self._headings) > 1:
                QtWidgets.QToolTip.showText(event.globalPos(), "点击展开或折叠，拖动整组排序", self,
                                           QtCore.QRect(0, i * ROW_H, self.width(), ROW_H))
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


class GameCalendarPage(Page):
    key, glyph, title, height = "calendar", G.CALENDAR, "活动日历", 450
    REFRESH_SECONDS = 1800
    deadlines_changed = QtCore.Signal(int)
    daily_reminders_changed = QtCore.Signal(object)
    game_order_changed = QtCore.Signal()

    def __init__(self, ctx):
        super().__init__(ctx)
        self._games = selected_games()
        self._data: dict[str, GameCalendar] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._requested: dict[str, float] = {}
        self._collapsed: set[str] = set()
        saved = cfg.get("game_calendar.acknowledged")
        self._acknowledged = {key for key in saved if isinstance(key, str)} if isinstance(saved, list) else set()
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
        self._ack_all = IconButton(G.CHECK, 28, 13)
        self._ack_all.clicked.connect(self._acknowledge_deadlines)
        self._range = Label("", 12, W.Medium, level=2)
        self._range.setToolTip("北京时间")
        header = hbox(Label("活动日历", 15, W.DemiBold), self._range, None, prev, today, next_, self._reload, self._ack_all,
                      spacing=4, margins=(2, 0, 2, 0))

        self._ruler = _Timeline(ruler=True)
        self._scroll = ScrollArea()
        self._scroll.verticalScrollBar().setFixedWidth(SCROLL_W)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._timeline = _Timeline(scroll_area=self._scroll)
        self._timeline.game_clicked.connect(self._toggle_game)
        self._timeline.activity_clicked.connect(self._toggle_activity)
        self._timeline.game_reordered.connect(self._move_game)
        self._timeline.dragging_changed.connect(self._lock_during_drag)
        self._scroll.inner.setLayout(vbox(self._timeline, None, spacing=0))
        card = Card(radius=14)
        card.setLayout(vbox(hbox((self._ruler, 1), SCROLL_W, spacing=0), (self._scroll, 1), spacing=0))
        self._daily = DailyPanel(self)
        self._daily.reminders_changed.connect(self.daily_reminders_changed)
        self._daily_enabled = bool(cfg.get("game_daily.enabled", True))
        self._daily.setVisible(self._daily_enabled)
        self.setLayout(vbox(self._daily, header, (card, 1), spacing=8))
        self._render()

    def on_show(self):
        super().on_show()
        self._games = selected_games()
        self._refresh()
        self._sync_daily_monitoring()

    def on_hide(self):
        self._timeline.cancel_drag()
        super().on_hide()
        self._sync_daily_monitoring()

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
        self._sync_daily_monitoring()

    def _sync_daily_monitoring(self):
        if self._daily_enabled and (self._monitoring or self.active):
            self._daily.start()
        else:
            self._daily.stop()

    def set_games(self, games: list[str]):
        self._timeline.cancel_drag()
        self._games = games
        if self.active or self._monitoring:
            self._refresh()

    def reload_daily_logs(self):
        self._daily_enabled = bool(cfg.get("game_daily.enabled", True))
        self._daily.setVisible(self._daily_enabled)
        self._daily.stop()
        self._daily.reload_sources()
        self._sync_daily_monitoring()
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
        pending = {}
        for game in self._games:
            if data := self._data.get(game):
                for item in data.activities:
                    if now < item.end <= cutoff:
                        key = _activity_key(game, item)
                        if key not in self._acknowledged:
                            pending[key] = (game, item)
        return sorted(pending.values(), key=lambda entry: entry[1].end)

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

    def _lock_during_drag(self, dragging: bool):
        if self.island is not None:
            if dragging:
                self.island.locks.add("calendar-reorder")
            else:
                self.island.locks.discard("calendar-reorder")

    def _move_game(self, game: str, before: str):
        if game not in self._games or game == before or (before and before not in self._games):
            return
        games = [key for key in self._games if key != game]
        games.insert(games.index(before) if before else len(games), game)
        if games != self._games:
            cfg.set("game_calendar.games", games)
            self._games = games
            self._render()
            self.game_order_changed.emit()

    def _toggle_activity(self, game: str, item: Activity):
        self._acknowledged.symmetric_difference_update({_activity_key(game, item)})
        self._save_acknowledgments()

    def _acknowledge_deadlines(self):
        pending = self._upcoming_deadlines(datetime.now(BEIJING))
        if pending:
            self._acknowledged.update(_activity_key(game, item) for game, item in pending)
            self._save_acknowledgments()

    def _save_acknowledgments(self):
        cfg.set("game_calendar.acknowledged", sorted(self._acknowledged))
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
        self._ack_all.setEnabled(bool(deadlines))
        self._ack_all.setToolTip(f"确认 72 小时内到期的 {len(deadlines)} 项活动" if deadlines else "暂无待确认的临期活动")
        for game in self._games:
            collapsed = game in self._collapsed
            data = self._data.get(game)
            if data is None:
                note = "获取失败 · 可刷新重试" if game in self._failed and game not in self._pending else "正在获取…"
                rows.append(_Row(GAMES[game], note, game=game, collapsed=collapsed))
                continue
            items = [item for item in data.activities if item.end >= start and item.start < end]
            items.sort(key=lambda item: (
                item.end < now or _activity_key(game, item) in self._acknowledged,
                item.end < now,
                item.start > now,
                item.start if item.start > now else item.end,
                item.name,
            ))
            note = f"{data.version} 版本" if data.version else ""
            if not items:
                note = " · ".join(filter(None, (note, "这段时间暂无活动")))
            elif collapsed:
                note = " · ".join(filter(None, (note, f"{len(items)} 项活动")))
            if game in self._failed:
                note = " · ".join(filter(None, (note, "刷新失败 · 上次数据")))
            rows.append(_Row(GAMES[game], note, game=game, collapsed=collapsed))
            if not collapsed:
                rows.extend(_Row(item.name, activity=item, game=game, tone=colors[game, item],
                                 acknowledged=_activity_key(game, item) in self._acknowledged) for item in items)
        if not rows:
            rows.append(_Row("未选择游戏", "在「设置 → 活动日历」里选择"))
        self._ruler.set_window(start, now, [], deadlines)
        self._timeline.set_window(start, now, rows)
        if self._monitoring:
            self.deadlines_changed.emit(len(deadlines))
