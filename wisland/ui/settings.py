# -*- coding: utf-8 -*-
"""独立设置窗口。

以前的"设置"是右键菜单里的几项（主题 / 展开方式 / 可穿透…），塞不下也不直观。
现在是一个独立窗口：左侧分类、右侧内容，改完立即生效并写回 config.json。

分类：外观 / 页面 / 控制中心 / 通知与应用 / Clash / 快捷键 / 关于
"""
from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid

from ..core import bg
from ..core.config import CONFIG_PATH, DATA_DIR, ROOT, cfg, expand
from ..services.game_calendar import GAMES, selected_games
from ..services.game_daily import LOG_SOURCES, locate_logs, log_settings
from .pagelayout import PAGE_INFO, page_layout, save_page_layout
from .theme import THEME_NAMES, G, W, icon_font, theme, ui_font
from .widgets import Card, Hoverable, IconButton, Label, Segmented, Sparkline, hbox, painter, vbox

Qt = QtCore.Qt

THEME_KEYS = [m for m, _ in THEME_NAMES]
THEME_LABELS = ["自动", "浅色", "深色", "胭脂", "晴空"]
EXPAND_KEYS = ["hover", "always", "never"]
EXPAND_LABELS = ["悬停展开", "常驻展开", "长关"]


def _bg() -> QtGui.QColor:
    return QtGui.QColor(28, 28, 32, 252) if theme.dark else QtGui.QColor(250, 250, 252, 253)


class Toggle(QtWidgets.QWidget):
    """迷你开关：42×24 的胶囊 + 圆点，带一点弹簧动画。"""
    toggled = QtCore.Signal(bool)

    def __init__(self, on: bool = False, parent=None):
        super().__init__(parent)
        self.on = bool(on)
        self.pos_ = 1.0 if on else 0.0
        self.setFixedSize(42, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = QtCore.QTimer(self, interval=16, timeout=self._tick)
        theme.changed.connect(self.update)

    def set_on(self, on: bool, emit: bool = False):
        on = bool(on)
        if on == self.on:
            return
        self.on = on
        self._t.start()
        if emit:
            self.toggled.emit(on)

    def _tick(self):
        target = 1.0 if self.on else 0.0
        self.pos_ += (target - self.pos_) * 0.35
        if abs(target - self.pos_) < 0.02:
            self.pos_ = target
            self._t.stop()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.set_on(not self.on, emit=True)

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(1, 3, self.width() - 2, self.height() - 6)
        t = max(0.0, min(1.0, self.pos_))
        off = theme.track()
        on = theme.on_color() if theme.dark else QtGui.QColor("#3b82f6")
        col = QtGui.QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.x() + 2 + (r.width() - d - 4) * t
        p.setBrush(QtGui.QColor("white"))
        p.drawEllipse(QtCore.QRectF(x, r.y() + 2, d, d))


class Row(QtWidgets.QWidget):
    """一行设置项：左边标题 + 说明，右边控件。"""

    def __init__(self, title: str, desc: str = "", widget: QtWidgets.QWidget | None = None, parent=None):
        super().__init__(parent)
        t = Label(title, 13, W.Medium)
        lay = QtWidgets.QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(t)
        if desc:
            lay.addWidget(WrapLabel(desc, 11.5, level=3))
        left = QtWidgets.QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        left.addLayout(lay)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(14, 9, 14, 9)
        h.setSpacing(12)
        h.addLayout(left, 1)
        if widget is not None:
            if isinstance(widget, QtWidgets.QLayout):
                h.addLayout(widget)
            else:
                h.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class Group(QtWidgets.QWidget):
    """一个小标题 + 一张卡片（多行）。"""

    def __init__(self, title: str, rows: list[QtWidgets.QWidget], parent=None):
        super().__init__(parent)
        card = Card(radius=16)
        lay = QtWidgets.QVBoxLayout()
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(0)
        for r in rows:
            lay.addWidget(r)
        card.setLayout(lay)
        cap = Label(title, 12, W.DemiBold, level=2) if title else None
        outer = vbox(cap, card, spacing=6) if cap is not None else vbox(card)
        self.setLayout(outer)


class Field(QtWidgets.QLineEdit):
    """设置里用的输入框（普通窗口，不需要灵动岛那套抢焦点的处理）。"""

    def __init__(self, text: str = "", placeholder: str = "", width: int = 240, parent=None):
        super().__init__(text, parent)
        self.error = False
        self.setPlaceholderText(placeholder)
        self.setFixedWidth(width)
        self.setFixedHeight(30)
        theme.changed.connect(self._style)
        self._style()

    def set_error(self, on: bool):
        on = bool(on)
        if on == self.error:
            return
        self.error = on
        self._style()

    def _style(self):
        bg = "rgba(255,255,255,18)" if theme.dark else "#ffffff"
        if self.error:
            bd = "rgba(255,90,90,190)"
        else:
            bd = "rgba(255,255,255,40)" if theme.dark else "rgba(0,0,0,30)"
        fg = theme.qss_color(theme.text())
        self.setStyleSheet(
            f"QLineEdit{{background:{bg};border:1px solid {bd};border-radius:8px;padding:0 10px;"
            f"color:{fg};selection-background-color:rgba(79,140,255,120)}}")


class WrapLabel(Label):
    """会自动换行的说明文字。Label 默认按单行算高度，换行后第二行会压到下面一行上去，
    这里把 heightForWidth 补上，让布局真的按行数留高度。"""

    def __init__(self, text: str, px: float = 11.5, weight=W.Normal, level: int = 3, parent=None):
        super().__init__(text, px, weight, level, parent, wrap=True)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumHeight(int(QtGui.QFontMetrics(self.font_).height() + 2))

    def heightForWidth(self, w: int) -> int:
        fm = QtGui.QFontMetrics(self.font_)
        r = fm.boundingRect(QtCore.QRect(0, 0, max(60, w), 4000),
                            int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft), self.text())
        return max(fm.height() + 2, r.height() + 2)


class Glyph(Label):
    """图标字。Label 用的是正文字体，直接放私用区码位会被系统兜底成汉字，这里换成图标字体。"""

    def __init__(self, ch: str, px: float = 14, level: int = 2, parent=None):
        super().__init__(ch, px, W.Normal, level, parent, align=Qt.AlignmentFlag.AlignCenter)
        self.font_ = icon_font(px)
        self.setFixedSize(int(px) + 12, int(px) + 10)


class FlatButton(QtWidgets.QPushButton):
    """设置窗口里的轻按钮。QPushButton 默认配色在浅色背景上几乎是白字白底，必须自己上色。"""

    def __init__(self, text: str, parent=None, accent: bool = False):
        super().__init__(text, parent)
        self.accent = accent
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        theme.changed.connect(self._style)
        self._style()

    def _style(self):
        if self.accent:
            bg = theme.qss_color(theme.accent)
            hover = theme.qss_color(theme.accent.lighter(112))
            fg = "#ffffff"
        elif theme.dark:
            bg, hover = "rgba(255,255,255,20)", "rgba(255,255,255,34)"
            fg = theme.qss_color(theme.text(0.9))
        else:
            bg, hover = "rgba(0,0,0,12)", "rgba(0,0,0,24)"
            fg = theme.qss_color(theme.text(0.86))
        self.setStyleSheet(
            f"QPushButton{{background:{bg};border:none;border-radius:8px;"
            f"padding:0 14px;color:{fg};font-size:12px}}"
            f"QPushButton:hover{{background:{hover}}}")


class NavItem(Hoverable):
    """左侧分类。"""

    def __init__(self, glyph: str, text: str, parent=None):
        super().__init__(parent)
        self.glyph, self.text = glyph, text
        self.active = False
        self.setFixedHeight(36)

    def set_active(self, on: bool):
        if on != self.active:
            self.active = on
            self.update()

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self.active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.active_pill())
            p.drawRoundedRect(r, 10, 10)
        elif self._hover.x > 0.01:
            c = theme.hover()
            c.setAlphaF(c.alphaF() * self._hover.x)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 10, 10)
        fg = theme.pill_text() if self.active else theme.text(0.88 if self._hover.x > 0.3 else 0.7)
        p.setFont(icon_font(13))
        p.setPen(fg)
        p.drawText(QtCore.QRectF(r.x() + 12, r.y(), 20, r.height()), Qt.AlignmentFlag.AlignCenter, self.glyph)
        p.setFont(ui_font(13, W.Medium if self.active else W.Normal))
        p.drawText(QtCore.QRectF(r.x() + 38, r.y(), r.width() - 44, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class PageRow(QtWidgets.QWidget):
    """页面清单里的一行：图标 + 名称 + 说明 + 上移 / 下移 / 显示开关。"""
    moved = QtCore.Signal(int)           # -1 上移 / +1 下移
    toggled = QtCore.Signal(str, bool)   # key, visible

    def __init__(self, key: str, visible: bool, first: bool, last: bool, parent=None):
        super().__init__(parent)
        self.key = key
        title, glyph, desc = PAGE_INFO.get(key, (key, G.APPS, ""))
        self.icon = Glyph(glyph, 14)
        self.icon.setFixedWidth(22)
        self.title = Label(title, 13, W.Medium)
        self.title.setFixedWidth(52)
        self.desc = Label(desc, 11.5, level=3)
        self.up = IconButton(G.UP, 26, 11, "上移")
        self.down = IconButton(G.DOWN, 26, 11, "下移")
        self.sw = Toggle(visible)
        self.up.setEnabled(not first)
        self.down.setEnabled(not last)
        self.up.clicked.connect(lambda: self.moved.emit(-1))
        self.down.clicked.connect(lambda: self.moved.emit(1))
        self.sw.toggled.connect(lambda on: self.toggled.emit(self.key, on))
        lay = hbox(self.icon, self.title, (self.desc, 1), self.up, self.down, self.sw, spacing=8, margins=(14, 6, 12, 6))
        self.setLayout(lay)
        self.setFixedHeight(46)


class DailyLogEditor(QtWidgets.QWidget):
    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change
        self._revision = 0
        self._fields = {}
        self._badges = {}
        self._buttons = {}
        self._enabled = Toggle(bool(cfg.get("game_daily.enabled", True)))
        self._enabled.toggled.connect(self._toggle)
        root, folders = log_settings()
        rows = [Row("显示今日日常", "开启后在活动日历上方读取本地脚本日志", self._enabled)]
        for key, title in [("root", "脚本总目录"), *((k, source[0]) for k, source in LOG_SOURCES.items())]:
            field = Field(root if key == "root" else folders.get(key, ""), "留空自动查找", width=214)
            field.editingFinished.connect(lambda k=key: self._save(k))
            pick = FlatButton("浏览")
            pick.clicked.connect(lambda _checked=False, k=key, t=title: self._browse(k, t))
            status = Label("", 11, level=3)
            self._fields[key] = field
            self._buttons[key] = pick
            self._badges[key] = status
            rows.append(Row(title, widget=hbox(status, field, pick, spacing=5)))
        hint = WrapLabel("总目录留空时尝试固定磁盘根目录下的 mihoyoMOD。也可为每个脚本选择安装目录或日志目录。",
                         11.5, level=3)
        self.setLayout(vbox(Group("今日日常日志", rows), hint, spacing=6))
        self._set_inputs_enabled(self._enabled.on)

    def _set_inputs_enabled(self, on: bool):
        for key, field in self._fields.items():
            field.setEnabled(on)
            self._buttons[key].setEnabled(on)

    def _toggle(self, on: bool):
        cfg.set("game_daily.enabled", on)
        self._set_inputs_enabled(on)
        self.check_locations()
        self._on_change()

    def _browse(self, key: str, title: str):
        field = self._fields[key]
        initial = field.text() or self._fields["root"].text()
        if key != "root" and not field.text():
            initial = self._badges[key].toolTip() or initial
        path = QtWidgets.QFileDialog.getExistingDirectory(self, f"选择{title}目录", expand(initial))
        if path:
            field.setText(path)
            self._save(key)

    def _save(self, key: str):
        value = self._fields[key].text().strip()
        root, folders = log_settings()
        if key == "root":
            if value == root:
                return
            cfg.set("game_daily.root", value)
        else:
            if value == folders.get(key, ""):
                return
            if value:
                folders[key] = value
            else:
                folders.pop(key, None)
            cfg.set("game_daily.folders", folders)
        self.check_locations()
        self._on_change()

    def check_locations(self):
        self._revision += 1
        for key in LOG_SOURCES:
            self._badges[key].setText("检测中…" if self._enabled.on else "")
            self._badges[key].setToolTip("")
        if self._enabled.on:
            revision = self._revision
            bg.run_bg(locate_logs, *log_settings(),
                      on_done=lambda locations: self._show_locations(revision, locations),
                      on_error=lambda _error: self._show_locations(revision, {}))

    def _show_locations(self, revision, locations):
        if not isValid(self) or revision != self._revision:
            return
        for key in LOG_SOURCES:
            status = self._badges[key]
            location = locations.get(key)
            status.setText("已找到" if location and location.found else "未找到")
            status.setToolTip(str(location.folder) if location else "")



class LauncherEditor(QtWidgets.QWidget):
    """主页快速应用：总开关、添加、重命名和删除。"""

    def __init__(self, on_changed=None, parent=None):
        super().__init__(parent)
        self.on_changed = on_changed
        self.items = [dict(x) for x in (cfg.get("launcher") or []) if isinstance(x, dict)]
        self.enabled = Toggle(bool(cfg.get("launcher_enabled", True)))
        self.enabled.toggled.connect(self._set_enabled)
        self.list_widget = QtWidgets.QWidget()
        self.list_lay = QtWidgets.QVBoxLayout(self.list_widget)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(4)
        add = FlatButton("添加应用…", accent=True)
        add.clicked.connect(self._add)
        self.setLayout(vbox(Group("主页快速应用", [
            Row("显示快速应用", "关闭后主页底部整条快捷应用栏都会隐藏", self.enabled),
            self.list_widget,
            Row("应用列表", "选择 exe 后可修改显示名称；删除会立即生效", add),
        ])))
        self._rebuild()

    def _notify(self):
        cfg.set("launcher", self.items)
        if self.on_changed:
            self.on_changed()

    def _set_enabled(self, on: bool):
        cfg.set("launcher_enabled", bool(on))
        self.list_widget.setEnabled(bool(on))
        if self.on_changed:
            self.on_changed()

    def _clear(self):
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _rebuild(self):
        self._clear()
        self.list_widget.setEnabled(self.enabled.on)
        if not self.items:
            self.list_lay.addWidget(WrapLabel("还没有应用，点击下面的“添加应用…”选择程序。", 11.5, level=3))
            return
        for item in self.items:
            name = Field(str(item.get("name") or ""), "显示名称", width=140)
            path = Field(expand(item.get("path") or ""), "程序路径", width=300)
            remove = FlatButton("删除")
            name.editingFinished.connect(lambda it=item, w=name: self._edit(it, "name", w.text().strip()))
            path.editingFinished.connect(lambda it=item, w=path: self._edit(it, "path", _norm_path(w.text())))
            remove.clicked.connect(lambda _=False, it=item: self._remove(it))
            row = QtWidgets.QWidget()
            row.setLayout(hbox(name, path, remove, spacing=6, margins=(10, 4, 10, 4)))
            self.list_lay.addWidget(row)

    def _edit(self, item: dict, key: str, value: str):
        item[key] = value
        self._notify()

    def _remove(self, item: dict):
        if item in self.items:
            self.items.remove(item)
            self._notify()
            self._rebuild()

    def _add(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择应用", "", "应用程序 (*.exe);;所有文件 (*)")
        if not path:
            return
        self.items.append({"name": os.path.splitext(os.path.basename(path))[0], "path": _norm_path(path)})
        self._notify()
        self._rebuild()


class SettingsWindow(QtWidgets.QWidget):
    """设置窗口本体。hooks: {"apply_pages": fn, "quit": fn}"""

    SECTIONS = [
        ("look", G.EYE, "外观"),
        ("pages", G.APPS, "页面"),
        ("calendar", G.CALENDAR, "活动日历"),
        ("controls", G.SLIDERS, "控制中心"),
        ("notify", G.BELL, "通知与应用"),
        ("clash", G.GLOBE, "Clash"),
        ("keys", G.SPEED, "快捷键"),
        ("about", G.GEAR, "关于"),
    ]

    def __init__(self, ctx, hooks: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.ctx = ctx
        self.hooks = hooks or {}
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("wisland 设置")
        self.resize(800, 600)
        self.setMinimumSize(720, 520)
        self._drag = None
        self._nav: dict[str, NavItem] = {}
        self._pages: list[dict] = page_layout([p.key for p in ctx.island.all_pages])
        self._stacks: dict[str, QtWidgets.QWidget] = {}
        self._sliders: dict[str, object] = {}

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(14)

        # ---------------- 左侧分类 ----------------
        side = QtWidgets.QVBoxLayout()
        side.setSpacing(4)
        title = Label("设置", 17, W.Bold)
        side.addWidget(title)
        side.addSpacing(8)
        for key, glyph, text in self.SECTIONS:
            it = NavItem(glyph, text)
            it.clicked.connect(lambda k=key: self.show_section(k))
            self._nav[key] = it
            side.addWidget(it)
        side.addStretch(1)
        self.ver = Label("wisland · 本地修改版", 11, level=3)
        side.addWidget(self.ver)
        side_w = QtWidgets.QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(168)
        root.addWidget(side_w)

        # ---------------- 右侧内容 ----------------
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        self.head_title = Label("外观", 15, W.DemiBold)
        close = IconButton(G.CLOSE, 30, 13, "关闭（Esc）")
        close.clicked.connect(self.close)
        head.addWidget(self.head_title)
        head.addStretch(1)
        head.addWidget(close)
        right.addLayout(head)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        self.scroll.viewport().setStyleSheet("background:transparent")
        holder = QtWidgets.QWidget()
        holder.setObjectName("settingsHolder")
        holder.setStyleSheet("#settingsHolder{background:transparent}")
        self.holder_lay = QtWidgets.QVBoxLayout(holder)
        self.holder_lay.setContentsMargins(0, 0, 6, 0)
        self.holder_lay.setSpacing(14)
        self.scroll.setWidget(holder)
        right.addWidget(self.scroll, 1)
        root.addLayout(right, 1)

        self._build_all()
        self.show_section("look")
        theme.changed.connect(self.update)

    # ================================================================ 窗口外观
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.fillPath(path, _bg())
        p.strokePath(path, QtGui.QPen(theme.outline(), 1.0))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 56:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def show_section(self, key: str):
        for k, it in self._nav.items():
            it.set_active(k == key)
        for k, w in self._stacks.items():
            w.setVisible(k == key)
        self.head_title.setText(dict((k, t) for k, _, t in self.SECTIONS).get(key, "设置"))
        if key == "pages":
            self._rebuild_pages()
        elif key == "calendar":
            self._daily_logs.check_locations()

    # ================================================================ 各分类
    def _build_all(self):
        self._stacks["look"] = self._build_look()
        self._stacks["pages"] = self._build_pages()
        self._stacks["calendar"] = self._build_calendar()
        self._stacks["controls"] = self._build_controls()
        self._stacks["notify"] = self._build_notify()
        self._stacks["clash"] = self._build_clash()
        self._stacks["keys"] = self._build_keys()
        self._stacks["about"] = self._build_about()
        for w in self._stacks.values():
            self.holder_lay.addWidget(w)
        self.holder_lay.addStretch(1)

    # ---------------- 外观 ----------------
    def _build_look(self) -> QtWidgets.QWidget:
        cur_theme = cfg.get("island.theme", "auto")
        seg_theme = Segmented(THEME_LABELS, height=28)
        seg_theme.setMinimumWidth(340)
        seg_theme.set_index(THEME_KEYS.index(cur_theme) if cur_theme in THEME_KEYS else 0)

        def on_theme(i):
            m = THEME_KEYS[i]
            cfg.set("island.theme", m)
            theme.set_mode(m)
        seg_theme.changed.connect(on_theme)

        mode = self.ctx.island.expand_mode()
        seg_mode = Segmented(EXPAND_LABELS, height=28)
        seg_mode.setMinimumWidth(240)
        seg_mode.set_index(EXPAND_KEYS.index(mode) if mode in EXPAND_KEYS else 0)
        seg_mode.changed.connect(lambda i: self.ctx.island.set_expand_mode(EXPAND_KEYS[i]))

        hover = self._ms_slider("hover_expand_ms", 60, 600, " ms")
        collapse = self._ms_slider("collapse_delay_ms", 120, 1200, " ms")
        cycle = self._ms_slider("auto_cycle_s", 0, 120, " 秒")
        media_width = self._ms_slider("island.compact_media_width", 360, 760, " px", 10)
        poll = self._ms_slider("media.poll_ms", 100, 3000, " ms", 50)
        raw_stickers = str(cfg.get("island.sticker_dir", "march7stickers") or "march7stickers")
        sticker_path = expand(raw_stickers)
        if not os.path.isabs(sticker_path):
            sticker_path = str(ROOT / sticker_path)
        f_stickers = Field(sticker_path, "贴纸图片文件夹", width=320)
        f_stickers.editingFinished.connect(lambda: self._set_sticker_dir(f_stickers.text()))
        b_stickers = FlatButton("选择…")
        b_stickers.clicked.connect(lambda: self._choose_sticker_dir(f_stickers))

        t_pt = Toggle(self.ctx.island.passthrough())
        t_pt.toggled.connect(lambda on: self.ctx.island.set_passthrough(on))
        t_cap = Toggle(self.ctx.island.capture_visible())
        t_cap.toggled.connect(lambda on: self.ctx.island.set_capture_visible(on))
        t_fs = Toggle(bool(cfg.get("island.hide_fullscreen", False)))
        t_fs.toggled.connect(lambda on: self.ctx.island.set_fullscreen_visible(not on))
        t_dbl = Toggle(bool(cfg.get("island.double_click_long_off", True)))
        t_dbl.toggled.connect(lambda on: cfg.set("island.double_click_long_off", bool(on)))

        auto_get, auto_set = self.hooks.get("autostart_get"), self.hooks.get("autostart_set")
        auto_on = bool(auto_get()) if auto_get else False
        t_auto = Toggle(auto_on)
        if auto_set is not None:
            t_auto.toggled.connect(lambda on: auto_set(bool(on)))
        admin_get, admin_set = self.hooks.get("admin_start_get"), self.hooks.get("admin_start_set")
        t_admin = Toggle(bool(admin_get()) if admin_get else False)
        t_admin.setEnabled(admin_set is not None)
        if admin_set is not None:
            t_admin.toggled.connect(admin_set)

        w = QtWidgets.QWidget()
        w.setLayout(vbox(
            Group("基础", [
                Row("主题", "跟随背景自动 = 按身后画面亮度在浅色 / 深色之间切换（带 3 秒滞回）", seg_theme),
                Row("展开方式", "悬停展开：鼠标靠近展开、离开收起；长关：只在点击热键 / 托盘时展开", seg_mode),
            ]),
            Group("动效", [
                Row("悬停展开延迟", "鼠标停留在灵动岛上多久后展开", hover),
                Row("收起延迟", "鼠标离开后多久收起", collapse),
                Row("收起态轮换", "时间天气与小形象自动轮换的间隔，0 = 不轮换", cycle),
                Row("收起态音乐宽度", "歌名或歌词超过该长度时会在胶囊内左右滚动", media_width),
                Row("播放器刷新间隔", "播放状态的同步频率；调小更跟手，调大更省 CPU", poll),
                Row("贴纸图片文件夹", "主页和可穿透小形象共用；文件夹里放 png/jpg/webp/gif/bmp 即可", hbox(f_stickers, b_stickers, spacing=6)),
            ]),
            Group("交互", [
                Row("可穿透", "鼠标完全穿过灵动岛，只响应右键（适合贴在屏幕边缘时用）", t_pt),
                Row("参与截图 / 录屏", "关掉后截图和录屏里看不到灵动岛", t_cap),
                Row("前台全屏时隐藏", "玩游戏 / 看全屏视频时自动收起", t_fs),
                Row("双击切换长关", "双击灵动岛或页面空白处切换悬停展开与长关", t_dbl),
                Row("开机自启", "登录 Windows 后运行 Wisland", t_auto),
                Row("启动时请求管理员权限", "适用于以管理员身份运行的全屏游戏。开启后，低权限启动时会显示 Windows 确认框", t_admin),
            ]),
            spacing=14))
        return w

    def _ms_slider(self, key: str, lo: int, hi: int, unit: str, unit_div: int = 1):
        """把配置里的数值映射成 0..1 的滑块（显示成具体数值）。"""
        cur = int(cfg.get(key, lo) or 0)
        s = SparklessSlider(G.VOLUME)
        s.set_value((cur - lo) / max(1, hi - lo), animate=False)
        s.label = f"{cur}{unit}"
        s.moved.connect(lambda v, k=key, a=lo, b=hi, u=unit, d=unit_div: self._slider_changed(s, k, a, b, u, v, d))
        s.setFixedWidth(210)
        return s

    def _slider_changed(self, s, key, lo, hi, unit, v, unit_div=1):
        val = int(round(lo + (hi - lo) * v))
        if unit_div > 1:
            val = int(math_round(val, unit_div))
        s.label = f"{val}{unit}"
        s.update()
        cfg.set(key, val)

    def _set_sticker_dir(self, path: str):
        path = _norm_path(path)
        cfg.set("island.sticker_dir", path or "march7stickers")
        self.ctx.pages["home"].pet.reload_stickers()
        self.ctx.island.compact.reload_stickers()
        self.ctx.island._kick()

    def _choose_sticker_dir(self, field: Field):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择贴纸图片文件夹", field.text())
        if path:
            field.setText(path)
            self._set_sticker_dir(path)

    # ---------------- 页面 ----------------
    def _build_pages(self) -> QtWidgets.QWidget:
        self._pages_box = QtWidgets.QWidget()
        self._pages_lay = QtWidgets.QVBoxLayout(self._pages_box)
        self._pages_lay.setContentsMargins(0, 2, 0, 2)
        self._pages_lay.setSpacing(0)
        card = Card(radius=16)
        card.setLayout(self._pages_lay)
        reset = FlatButton("恢复默认顺序")
        reset.clicked.connect(self._reset_pages)
        hint = WrapLabel("隐藏的页面不会出现在导航里，也不会跑它自己的定时器（例如股票页隐藏后就不再请求行情）。",
                         11.5, level=3)
        w = QtWidgets.QWidget()
        w.setLayout(vbox(Group("页面显示与顺序", [hint]), card,
                         hbox(reset, None), spacing=12))
        self._rebuild_pages()
        return w

    def _rebuild_pages(self):
        if not hasattr(self, "_pages_lay"):
            return
        while self._pages_lay.count():
            it = self._pages_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, p in enumerate(self._pages):
            row = PageRow(p["key"], p["visible"], i == 0, i == len(self._pages) - 1)
            row.moved.connect(lambda d, i=i: self._move_page(i, d))
            row.toggled.connect(self._toggle_page)
            self._pages_lay.addWidget(row)

    def _move_page(self, i: int, delta: int):
        j = i + delta
        if not (0 <= j < len(self._pages)):
            return
        self._pages[i], self._pages[j] = self._pages[j], self._pages[i]
        self._apply_pages()

    def _toggle_page(self, key: str, visible: bool):
        for p in self._pages:
            if p["key"] == key:
                p["visible"] = bool(visible)
        if not any(p["visible"] for p in self._pages) and self._pages:
            self._pages[0]["visible"] = True       # 至少留一页，否则导航会空
        self._apply_pages()

    def _reset_pages(self):
        keys = [p.key for p in self.ctx.island.all_pages]
        self._pages = [{"key": k, "visible": True} for k in keys]
        self._apply_pages()

    def _apply_pages(self):
        save_page_layout(self._pages)
        self.ctx.island.apply_page_layout()
        self._pages = page_layout([p.key for p in self.ctx.island.all_pages])
        self._rebuild_pages()
        fn = self.hooks.get("apply_pages")
        if fn:
            fn()

    # ---------------- 活动日历 ----------------
    def _build_calendar(self) -> QtWidgets.QWidget:
        self._daily_logs = DailyLogEditor(self._reload_daily_logs)
        self._game_card = Card(radius=16)
        self._game_rows = QtWidgets.QVBoxLayout(self._game_card)
        self._game_rows.setContentsMargins(0, 2, 0, 2)
        self._game_rows.setSpacing(0)
        hint = WrapLabel("开启的游戏按下列顺序显示在活动日历。活动数据来自 StarRailAssistant 公共 API。", 11.5, level=3)
        w = QtWidgets.QWidget()
        w.setLayout(vbox(self._daily_logs, hint, self._game_card, spacing=12))
        self._rebuild_calendar()
        return w

    def _reload_daily_logs(self):
        page = self.ctx.island.page("calendar")
        if page:
            page.reload_daily_logs()

    def _rebuild_calendar(self):
        while self._game_rows.count():
            self._game_rows.takeAt(0).widget().deleteLater()
        games = selected_games()
        for game in games + [key for key in GAMES if key not in games]:
            sw = Toggle(game in games)
            sw.setAccessibleName(GAMES[game])
            sw.toggled.connect(lambda on, k=game: self._toggle_game(k, on))
            controls = hbox(sw, spacing=4)
            if game in games:
                i = games.index(game)
                up = IconButton(G.UP, 26, 11, "上移")
                down = IconButton(G.DOWN, 26, 11, "下移")
                up.setEnabled(i > 0)
                down.setEnabled(i < len(games) - 1)
                up.clicked.connect(lambda k=game: self._move_game(k, -1))
                down.clicked.connect(lambda k=game: self._move_game(k, 1))
                controls.insertWidget(0, down)
                controls.insertWidget(0, up)
            self._game_rows.addWidget(Row(GAMES[game], widget=controls))

    def _toggle_game(self, game: str, on: bool):
        games = selected_games()
        if on and game not in games:
            games.append(game)
        elif not on and game in games:
            games.remove(game)
        self._save_calendar(games)

    def _move_game(self, game: str, delta: int):
        games = selected_games()
        if game not in games:
            return
        i = games.index(game)
        j = i + delta
        if 0 <= j < len(games):
            games[i], games[j] = games[j], games[i]
            self._save_calendar(games)

    def _save_calendar(self, games: list[str]):
        cfg.set("game_calendar.games", games)
        page = self.ctx.island.page("calendar")
        if page:
            page.set_games(games)
        self._rebuild_calendar()

    # ---------------- 控制中心 ----------------
    def _build_controls(self) -> QtWidgets.QWidget:
        tiles = cfg.get("controls.tiles") or {}
        rows = []
        names = [("wifi", "WLAN 磁贴"), ("bt", "蓝牙磁贴"), ("hotspot", "移动热点磁贴"), ("audio", "声音输出磁贴")]
        for key, label in names:
            t = Toggle(bool(tiles.get(key, True)))
            t.toggled.connect(lambda on, k=key: self._set_tile(k, on))
            rows.append(Row(label, "", t))
        t_vol = Toggle(bool(cfg.get("controls.show_volume", True)))
        t_vol.toggled.connect(lambda on: self._set_ctl("show_volume", on))
        t_bri = Toggle(bool(cfg.get("controls.show_brightness", True)))
        t_bri.toggled.connect(lambda on: self._set_ctl("show_brightness", on))
        t_clash = Toggle(bool(cfg.get("controls.show_clash", True)))
        t_clash.toggled.connect(lambda on: self._set_ctl("show_clash", on))
        t_mixer = Toggle(bool(cfg.get("controls.show_mixer", True)))
        t_mixer.toggled.connect(lambda on: self._set_ctl("show_mixer", on))
        w = QtWidgets.QWidget()
        w.setLayout(vbox(
            Group("磁贴", rows),
            Group("滑块与卡片", [
                Row("音量滑块", "", t_vol),
                Row("亮度滑块", "没有可调亮度的显示器时可以关掉", t_bri),
                Row("Clash Verge 卡片", "检测到 Clash Verge 正在运行时才显示", t_clash),
                Row("应用音量合成器", "显示在系统开关列，最多显示 3 个应用，更多应用在卡片内滚动", t_mixer),
            ]),
            spacing=14))
        return w

    def _set_tile(self, key: str, on: bool):
        tiles = dict(cfg.get("controls.tiles") or {})
        tiles[key] = bool(on)
        cfg.set("controls.tiles", tiles)
        self._apply_controls()

    def _set_ctl(self, key: str, on: bool):
        cfg.set(f"controls.{key}", bool(on))
        self._apply_controls()

    def _apply_controls(self):
        page = self.ctx.pages.get("ctl") if hasattr(self.ctx, "pages") else None
        if page is not None:
            page.apply_visibility()

    # ---------------- 通知与应用 ----------------
    def _build_notify(self) -> QtWidgets.QWidget:
        rows = []
        for kind, label, tip in (
                ("qq", "QQ 路径", "留空 = 自动在运行中的进程 / 安装目录里找"),
                ("wechat", "微信路径", "留空 = 自动查找"),
                ("mail", "邮件客户端路径", "点消息页的「邮件」时会打开这个程序（默认找 Thunderbird）")):
            f = Field(expand(cfg.get(f"notify.open.{kind}") or ""), tip)
            f.editingFinished.connect(lambda k=kind, w=f: cfg.set(f"notify.open.{k}", _norm_path(w.text())))
            rows.append(Row(label, tip, f))

        hk_rows = []
        rh = dict(cfg.get("apps.restore_hotkey") or {})
        for exe, label, desc in (
                ("qq.exe", "QQ 显示窗口热键",
                 "可选。QQ 的快捷键存不住也没关系：留空时 wisland 会直接把它的托盘窗口拉出来"),
                ("weixin.exe", "微信显示窗口热键",
                 "可选。留空时直接用窗口唤出；微信默认 Ctrl+Alt+W，要和微信快捷键设置一致")):
            f = Field(rh.get(exe, ""), "如 Ctrl+Alt+Q（留空 = 直接唤出窗口）", width=200)
            f.textChanged.connect(lambda t, e=exe, w=f: self._set_hotkey(e, t.strip(), w))
            hk_rows.append(Row(label, desc, f))

        launcher = LauncherEditor(lambda: self.ctx.pages["home"].build_launcher())
        w = QtWidgets.QWidget()
        w.setLayout(vbox(
            launcher,
            Group("消息页点击「QQ / 微信 / 邮件」时打开什么", rows),
            Group("托盘唤出", hk_rows),
            spacing=14))
        return w

    def _set_hotkey(self, exe: str, spec: str, field: Field | None = None):
        """热键表整表读出来改完再写回。
        exe 名字本身带点（qq.exe），不能拼成 cfg.set("apps.restore_hotkey.qq.exe")，
        那样会被点号路径拆成 qq -> exe 两层，存进去就再也取不出来了。"""
        from ..services.system import hotkey_valid
        d = {k: v for k, v in (cfg.get("apps.restore_hotkey") or {}).items() if isinstance(v, str)}
        bad = bool(spec) and not hotkey_valid(spec)
        if field is not None:
            field.set_error(bad)
            field.setToolTip("要用修饰键：如 Ctrl+Alt+Q" if bad else "")
        if bad:
            return
        if spec:
            d[exe] = spec
        else:
            d.pop(exe, None)
        cfg.set("apps.restore_hotkey", d)

    # ---------------- Clash ----------------
    def _build_clash(self) -> QtWidgets.QWidget:
        f_app = Field(expand(cfg.get("clash.app") or ""), "留空 = 自动查找 clash-verge.exe", width=320)
        f_app.editingFinished.connect(lambda: cfg.set("clash.app", _norm_path(f_app.text())))
        auto = FlatButton("自动查找")
        auto.clicked.connect(lambda: self._find_clash(f_app))
        f_port = Field(str(cfg.get("clash.proxy_port") or 7897), "7897", width=100)
        f_port.editingFinished.connect(lambda: self._set_port(f_port))
        f_dir = Field(expand(cfg.get("clash.config_dir") or ""), "clash-verge 的配置目录", width=320)
        f_dir.editingFinished.connect(lambda: cfg.set("clash.config_dir", _norm_path(f_dir.text())))
        w = QtWidgets.QWidget()
        w.setLayout(vbox(
            Group("Clash Verge", [
                Row("程序路径", "控制页右上角的按钮用它来打开 / 唤出 Clash Verge", hbox(f_app, auto, spacing=6)),
                Row("系统代理端口", "切换「系统代理」时写入的 127.0.0.1:端口", f_port),
                Row("配置目录", "从这里读 secret 与 external-controller（用于连接 mihomo）", f_dir),
            ]),
            spacing=14))
        return w

    def _find_clash(self, field: Field):
        from ..services.system import resolve_app_path
        p = resolve_app_path("clash-verge.exe")
        if p:
            field.setText(p)
            cfg.set("clash.app", p)
        else:
            field.setText("")
            field.setPlaceholderText("没找到，请手动填写 clash-verge.exe 的完整路径")

    def _set_port(self, field: Field):
        try:
            port = int(field.text().strip() or 7897)
        except ValueError:
            port = 7897
        field.setText(str(port))
        cfg.set("clash.proxy_port", port)

    # ---------------- 快捷键 ----------------
    def _build_keys(self) -> QtWidgets.QWidget:
        rows = []
        hk = dict(cfg.get("hotkeys") or {})
        for key, label, desc in (("toggle", "展开 / 收起", "全局热键"),
                                 ("translate", "翻译剪贴板", "复制文字后按一下"),
                                 ("clipboard", "剪贴板历史", "")):
            f = Field(hk.get(key, ""), "例如 Ctrl+Alt+I", width=170)
            f.editingFinished.connect(lambda k=key, w=f: self._set_global_hotkey(k, w.text().strip()))
            rows.append(Row(label, desc, f))
        w = QtWidgets.QWidget()
        w.setLayout(vbox(Group("全局热键", rows),
                         WrapLabel("改完立即重新注册；提示「注册失败」说明被别的软件占用了。", 11.5, level=3),
                         spacing=14))
        return w

    def _set_global_hotkey(self, key: str, spec: str):
        cfg.set(f"hotkeys.{key}", spec)
        self.ctx.island.register_hotkeys()

    # ---------------- 关于 ----------------
    def _build_about(self) -> QtWidgets.QWidget:
        open_cfg = FlatButton("打开")
        open_cfg.clicked.connect(lambda: os.startfile(str(CONFIG_PATH)))  # noqa: S606
        open_data = FlatButton("打开")
        open_data.clicked.connect(lambda: os.startfile(str(DATA_DIR)))  # noqa: S606
        quit_btn = FlatButton("退出 wisland")
        quit_btn.clicked.connect(self._quit)
        w = QtWidgets.QWidget()
        w.setLayout(vbox(
            Group("", [
                Row("wisland", "Windows 液态灵动岛 · PySide6", None),
                Row("配置文件", str(CONFIG_PATH), open_cfg),
                Row("数据目录", "日志、锁文件、股票提醒记录等", open_data),
            ]),
            hbox(quit_btn, None),
            spacing=14))
        return w

    def _quit(self):
        fn = self.hooks.get("quit")
        if fn:
            fn()

    # ================================================================ 显示
    def present(self):
        self._pages = page_layout([p.key for p in self.ctx.island.all_pages])
        self._rebuild_pages()
        self.show()
        scr = self.screen() or QtGui.QGuiApplication.primaryScreen()
        g = scr.availableGeometry() if scr else self.geometry()
        size = QtCore.QSize(min(self.width(), max(720, g.width() - 40)),
                            min(self.height(), max(520, g.height() - 40)))
        self.resize(size)
        pos = g.center() - QtCore.QPoint(size.width() // 2, size.height() // 2)
        pos.setX(max(g.left(), min(pos.x(), g.right() + 1 - size.width())))
        pos.setY(max(g.top(), min(pos.y(), g.bottom() + 1 - size.height())))
        self.move(pos)
        if os.environ.get("WISLAND_DEBUG"):
            print(f"[dbg] settings avail={g} size={size} geo={self.geometry()}", flush=True)
        self.raise_()
        self.activateWindow()
        if os.environ.get("WISLAND_SHOT"):
            self._debug_shots()

    def _debug_shots(self):
        """调试用：依次切换分类并把窗口自身抓成 png（WISLAND_SHOT=look,pages,…）。"""
        keys = [k.strip() for k in os.environ.get("WISLAND_SHOT", "").split(",") if k.strip()]
        keys = keys or [k for k, _, _ in self.SECTIONS]
        out = os.path.join(DATA_DIR, "dbg")
        os.makedirs(out, exist_ok=True)

        def shot(key: str, idx: int):
            self.show_section(key)
            QtWidgets.QApplication.processEvents()
            p = os.path.join(out, f"set_{idx}_{key}.png")
            self.grab().save(p)
            print(f"[shot] {p} {self.size()}", flush=True)

        for i, k in enumerate(keys):
            QtCore.QTimer.singleShot(600 + i * 500, lambda k=k, i=i: shot(k, i))


def _norm_path(text: str) -> str:
    """设置里填的路径统一成本机的反斜杠形式；空串照旧。"""
    text = (text or "").strip().strip('"')
    return os.path.normpath(text) if text else ""


def math_round(v: float, div: int) -> float:
    return round(v / div) * div


class SparklessSlider(QtWidgets.QWidget):
    """设置窗口里的滑杆：细轨道 + 圆点，右侧显示具体数值。"""

    moved = QtCore.Signal(float)

    def __init__(self, glyph: str = "", parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.value = 0.0
        self.label = ""
        self.dragging = False
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.changed.connect(self.update)

    def set_value(self, v: float, animate: bool = True):
        self.value = max(0.0, min(1.0, float(v)))
        self.update()

    def _val_at(self, x: float) -> float:
        return max(0.0, min(1.0, x / max(1, self.width() - 62)))

    def mousePressEvent(self, e):
        self.dragging = True
        self.value = self._val_at(e.position().x())
        self.update()
        self.moved.emit(self.value)

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.value = self._val_at(e.position().x())
            self.update()
            self.moved.emit(self.value)

    def mouseReleaseEvent(self, e):
        self.dragging = False

    def wheelEvent(self, e):
        e.ignore()

    def paintEvent(self, e):
        p = painter(self)
        w = max(1, self.width() - 62)
        track = QtCore.QRectF(0, self.height() / 2 - 2, w, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.track())
        p.drawRoundedRect(track, 2, 2)
        fw = max(4.0, w * self.value)
        p.setBrush(theme.accent)
        p.drawRoundedRect(QtCore.QRectF(0, track.y(), fw, 4), 2, 2)
        p.setBrush(QtGui.QColor("white") if not theme.dark else theme.text())
        p.drawEllipse(QtCore.QPointF(fw, self.height() / 2), 6, 6)
        p.setFont(ui_font(11.5, W.Medium, num=True))
        p.setPen(theme.text2())
        p.drawText(QtCore.QRectF(w + 8, 0, 54, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.label)


_ = Sparkline  # 保留导入（个别分支会用到）
