# -*- coding: utf-8 -*-
"""主页（正在播放 + 快捷操作 + 自定义启动器）与消息页（QQ / 微信 / 邮件提醒）。"""
from __future__ import annotations

import os
import random
import time

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.bg import launch
from ...core.config import cfg, expand
from ..anim import Spring, clamp
from ..stickers import load_sticker, sticker_paths
from ..theme import KIND_COLORS, G, W, icon_font, theme, ui_font
from ..widgets import (Card, Hoverable, IconButton, Label, PillButton, ScrollArea, Themed, fmt_time, hbox,
                       painter, rounded_pixmap, vbox)
from .base import Page

Qt = QtCore.Qt


# ======================================================================== 播放卡片
class Progress(QtWidgets.QWidget, Themed):
    seek = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.pos_ = 0.0
        self.dur = 0.0
        self.stamp = 0.0
        self.playing = False
        self.hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hook_theme()

    def set_state(self, m: dict):
        self.pos_ = float(m.get("position") or 0)
        self.dur = float(m.get("duration") or 0)
        self.stamp = float(m.get("stamp") or time.monotonic())
        self.playing = bool(m.get("playing"))
        self.update()

    def current(self) -> float:
        p = self.pos_ + ((time.monotonic() - self.stamp) if self.playing else 0)
        return clamp(p, 0, self.dur) if self.dur else p

    def mouseReleaseEvent(self, e):
        if self.dur > 0:
            self.seek.emit(clamp(e.position().x() / max(1, self.width()), 0, 1) * self.dur)

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect())
        y = 6
        th = 4 + 3 * self.hover
        tr = QtCore.QRectF(0, y - th / 2, r.width(), th)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.track())
        p.drawRoundedRect(tr, th / 2, th / 2)
        cur = self.current()
        if self.dur > 0:
            p.setBrush(theme.text(0.85 + 0.15 * self.hover))
            p.drawRoundedRect(QtCore.QRectF(0, y - th / 2, max(th, r.width() * cur / self.dur), th), th / 2, th / 2)
        p.setFont(ui_font(10.5, num=True))
        p.setPen(theme.text3())
        p.drawText(QtCore.QRectF(0, 10, 60, 12), Qt.AlignmentFlag.AlignLeft, fmt_time(cur))
        if self.dur > 0:
            p.drawText(QtCore.QRectF(r.width() - 60, 10, 60, 12), Qt.AlignmentFlag.AlignRight, fmt_time(self.dur))


class CoverView(QtWidgets.QWidget):
    """封面：悬停时轻微放大上浮，并在身后透出封面主色的柔光。"""
    def __init__(self, size: int, parent=None):
        super().__init__(parent)
        self.size_ = size
        self.pm: QtGui.QPixmap | None = None
        self.glow = QtGui.QColor(255, 255, 255, 0)
        self.h = 0.0
        self.setFixedSize(size + 12, size + 12)

    def set_pixmap(self, pm, glow: QtGui.QColor | None):
        self.pm = pm
        self.glow = glow or QtGui.QColor(255, 255, 255, 0)
        self.update()

    def paintEvent(self, e):
        p = painter(self)
        c = QtCore.QRectF(self.rect()).center()
        s = 1.0 + 0.07 * self.h
        r = QtCore.QRectF(0, 0, self.size_ * s, self.size_ * s)
        r.moveCenter(c - QtCore.QPointF(0, 2.5 * self.h))
        if self.h > 0.01 and self.glow.alpha():
            g = QtGui.QRadialGradient(r.center() + QtCore.QPointF(0, 6), r.width() * 0.75)
            col = QtGui.QColor(self.glow)
            col.setAlpha(round(150 * self.h))
            g.setColorAt(0, col)
            col2 = QtGui.QColor(self.glow)
            col2.setAlpha(0)
            g.setColorAt(1, col2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(r.adjusted(-8, -4, 8, 14))
        if self.pm is not None:
            p.drawPixmap(r.toRect(), self.pm)


class CoverTitle(QtWidgets.QWidget):
    """封面在上方居中；歌名和歌手在封面下方独立排布，互不重叠。"""
    clicked = QtCore.Signal()
    COVER = 87       # 原 58px 的 1.5 倍

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm: QtGui.QPixmap | None = None
        self.glow = QtGui.QColor(255, 255, 255, 0)
        self.h = 0.0
        self.title = "未在播放"
        self.sub = ""
        self.setFixedHeight(self.COVER + 48)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击唤出网易云音乐")
        theme.changed.connect(self.update)

    def set_pixmap(self, pm, glow):
        self.pm = pm
        self.glow = glow or QtGui.QColor(255, 255, 255, 0)
        self.update()

    def set_text(self, title, sub):
        self.title, self.sub = title, sub
        self.update()

    def _cover_rect(self) -> QtCore.QRectF:
        s = 1.0 + 0.07 * self.h
        size = self.COVER * s
        cr = QtCore.QRectF(0, 0, size, size)
        cr.moveCenter(QtCore.QPointF(self.width() / 2, 4 + self.COVER / 2 - 2.5 * self.h))
        return cr

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._cover_rect().contains(e.position()):
            self.clicked.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = painter(self)
        W_ = self.width()
        cr = self._cover_rect()
        if self.h > 0.01 and self.glow.alpha():
            g = QtGui.QRadialGradient(cr.center() + QtCore.QPointF(0, 6), cr.width() * 0.8)
            c1 = QtGui.QColor(self.glow)
            c1.setAlpha(round(150 * self.h))
            c2 = QtGui.QColor(self.glow)
            c2.setAlpha(0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(cr.adjusted(-10, -6, 10, 14))
        if self.pm is not None:
            p.drawPixmap(cr.toRect(), self.pm)
        # 两行信息完全放在封面下方：第一行歌名，第二行歌手。
        title_font = ui_font(12.5, W.DemiBold)
        artist_font = ui_font(10.5, W.Medium)
        title_fm = QtGui.QFontMetrics(title_font)
        artist_fm = QtGui.QFontMetrics(artist_font)
        maxw = W_ - 20
        title = title_fm.elidedText(self.title, Qt.TextElideMode.ElideRight, int(maxw))
        artist = artist_fm.elidedText(self.sub, Qt.TextElideMode.ElideRight, int(maxw)) if self.sub else ""
        text_top = 4 + self.COVER + 5
        title_r = QtCore.QRectF(10, text_top, maxw, 20)
        artist_r = QtCore.QRectF(10, text_top + 21, maxw, 17)
        p.setFont(title_font)
        p.setPen(theme.text())
        p.drawText(title_r, Qt.AlignmentFlag.AlignCenter, title)
        if artist:
            p.setFont(artist_font)
            p.setPen(theme.text2())
            p.drawText(artist_r, Qt.AlignmentFlag.AlignCenter, artist)


class MediaCard(Card):
    def __init__(self, ctx, parent=None):
        super().__init__(parent, 20)
        self.ctx = ctx
        self.cover_px: QtGui.QPixmap | None = None
        self.cover = CoverTitle(self)
        self._hov = Spring(0, 260, 0.6, 0.004)
        self._ht = QtCore.QTimer(self, interval=16, timeout=self._hover_tick)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.title = Label("未在播放", 15, W.DemiBold)
        self.artist = Label("", 12.5, level=2)
        self.app = Label("", 11, level=3)
        self.prog = Progress()
        self.like = IconButton(G.HEART, 34, 15, "喜欢 / 取消喜欢（网易云）")
        self.prev = IconButton(G.PREV, 34, 15, "上一首")
        self.play = IconButton(G.PLAY, 40, 18, "播放 / 暂停", filled=True)
        self.next = IconButton(G.NEXT, 34, 15, "下一首")
        self.open_btn = PillButton("打开网易云", G.MUSIC, height=28)
        self.like.clicked.connect(lambda: ctx.media.like())
        self.prev.clicked.connect(lambda: ctx.media.prev())
        self.next.clicked.connect(lambda: ctx.media.next())
        self.play.clicked.connect(lambda: ctx.media.play_pause())
        self.prog.seek.connect(lambda s: ctx.media.seek(s))
        self.cover.clicked.connect(self._open_player)
        self.open_btn.clicked.connect(self._open_player)
        self.open_btn.hide()
        self.title.hide()
        self.artist.hide()
        self.app.hide()
        ctrls = hbox(None, self.like, self.prev, self.play, self.next, None, spacing=6)   # 播放键正对封面
        self.setLayout(vbox(self.cover, self.prog, ctrls, None, spacing=0, margins=(10, 6, 10, 6)))
        self._tick = QtCore.QTimer(self, interval=500, timeout=self.prog.update)
        self._set_cover(None)

    # --- 悬停动画 ---
    def enterEvent(self, e):
        self._hov.to(1.0, 260, 0.6)
        self._ht.start()

    def leaveEvent(self, e):
        self._hov.to(0.0, 220, 0.8)
        self._ht.start()

    def _hover_tick(self):
        self._hov.step(0.016)
        h = max(0.0, self._hov.x)
        self.cover.h = h
        self.cover.update()
        self.prog.hover = h
        self.prog.update()
        self.update()
        if self._hov.rest:
            self._ht.stop()

    def paintEvent(self, e):
        """不画独立背景，直接嵌在灵动岛玻璃上（悬停时封面 / 进度条有动画）。"""
        return

    def _open_player(self):
        """点击专辑封面时唤出网易云：有窗口就切过去，没运行（或只剩后台进程）就启动。"""
        hints = ("网易云音乐", "NetEase CloudMusic", "CloudMusic")
        args = None
        if self.ctx.windows.reveal("cloudmusic.exe", hints, allow_hidden=True):
            result, path = "focused", ""
        else:
            items = cfg.get("launcher") or []
            it = next((i for i in items if "cloudmusic" in str(i.get("path", "")).lower()), None)
            if it:
                path = expand(it.get("path") or "cloudmusic.exe")
                args = it.get("args")
                result = self.ctx.windows.open_or_focus(path, it.get("exe") or "cloudmusic.exe", args)
            else:
                from ...services.system import resolve_app_path
                path = resolve_app_path("cloudmusic.exe") or "cloudmusic.exe"
                result = self.ctx.windows.open_or_focus(path, "cloudmusic.exe")
            # 网易云常驻托盘时进程还在、却没有窗口，open_or_focus 只会提示「去配显示热键」而不启动。
            # 它是单实例应用，再启动一次就会把自己的窗口调出来，所以这里补一次兜底启动。
            if result == "failed" and path and os.path.exists(path):
                extra = args.split() if isinstance(args, str) else list(args or [])
                result = "launched" if launch(path, extra) else "failed"
        if result in ("focused", "launched") and getattr(self.ctx, "island", None):
            self.ctx.island.collapse()

    def _set_cover(self, img):
        cover_size = CoverTitle.COVER
        cover_radius = round(cover_size * 13 / 58)
        px = rounded_pixmap(img, cover_size, cover_radius) if img is not None else None
        glow = None
        if img is not None:
            q = img if isinstance(img, QtGui.QImage) else img.toImage()
            glow = q.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation).pixelColor(0, 0)
            h, s_, v, _ = glow.getHsv()
            glow = QtGui.QColor.fromHsv(max(0, h), min(255, int(s_ * 1.4) + 40), max(170, v))
        if px is None:
            physical = cover_size * 2
            pm = QtGui.QPixmap(physical, physical)
            pm.fill(Qt.GlobalColor.transparent)
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.card(1.6))
            p.drawRoundedRect(QtCore.QRectF(0, 0, physical, physical), cover_radius * 2, cover_radius * 2)
            p.setFont(icon_font(66))
            p.setPen(theme.text(0.6))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, G.MUSIC)
            p.end()
            pm.setDevicePixelRatio(2)
            px = pm
        self.cover.set_pixmap(px, glow)

    def set_cover(self, img):
        self._set_cover(img)

    def set_media(self, m: dict):
        has = bool(m.get("has_session") and m.get("title"))
        self.cover.set_text(m.get("title") or "未在播放", m.get("artist") or "")
        self.play.set_glyph(G.PAUSE if m.get("playing") else G.PLAY)
        liked = m.get("liked") is True
        self.like.set_glyph(G.HEART_FILL if liked else G.HEART)
        self.like.color = QtGui.QColor("#EC4141") if liked else None
        self.like.setToolTip("已喜欢，点击取消喜欢" if liked else "喜欢当前歌曲（网易云）")
        self.like.update()
        self.prog.set_state(m)
        self.prog.setVisible(True)
        self.prog.setEnabled(has and (m.get("duration") or 0) > 0)
        # 按钮始终可用：没有媒体会话（播放器没接入系统媒体控件）时会改发键盘媒体键

        if m.get("playing"):
            self._tick.start()
        else:
            self._tick.stop()


# ======================================================================== 快捷操作 / 启动器
class Action(Hoverable):
    def __init__(self, glyph: str, title: str, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.title = title
        self.on = False
        self.setFixedHeight(58)

    def set_on(self, on: bool, glyph: str | None = None, title: str | None = None):
        self.on = on
        if glyph:
            self.glyph = glyph
        if title:
            self.title = title
        self.update()

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        sc = self.press_scale()
        p.translate(r.center())
        p.scale(sc, sc)
        p.translate(-r.center())
        if self._hover.x > 0.01:
            c = theme.hover()
            c.setAlphaF(c.alphaF() * self._hover.x)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 16, 16)
        col = theme.on_color() if self.on else theme.text(0.9)
        p.setFont(icon_font(18))
        p.setPen(col)
        p.drawText(QtCore.QRectF(r.x(), r.y() + 6, r.width(), 26), Qt.AlignmentFlag.AlignCenter, self.glyph)
        p.setFont(ui_font(11.5, W.DemiBold if self.on else W.Medium))
        p.setPen(theme.on_color() if self.on else theme.text2())
        p.drawText(QtCore.QRectF(r.x(), r.y() + 32, r.width(), 18), Qt.AlignmentFlag.AlignCenter, self.title)


_icon_provider = None


def file_icon(path: str, size: int = 64) -> QtGui.QPixmap | None:
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QtWidgets.QFileIconProvider()
    if not path or not os.path.exists(path):
        return None
    ic = _icon_provider.icon(QtCore.QFileInfo(path))
    pm = ic.pixmap(size, size)
    return None if pm.isNull() else pm


_appx_cache: dict[str, str] = {}


def resolve_appx(spec: str, cb):
    """"appx:包名/相对路径" -> 安装目录下的文件路径（后台查询，结果缓存）。"""
    from ...core.bg import run_bg, run_hidden
    name, _, rel = spec[5:].partition("/")
    if name in _appx_cache:
        cb(os.path.join(_appx_cache[name], rel))
        return

    def q():
        r = run_hidden(["powershell", "-NoProfile", "-Command", f"(Get-AppxPackage -Name '{name}').InstallLocation"])
        return (r.stdout or b"").decode("utf-8", "ignore").strip().splitlines()[0] if r.stdout else ""

    def done(loc):
        if loc:
            _appx_cache[name] = loc
            cb(os.path.join(loc, rel))
    run_bg(q, on_done=done)


class LaunchIcon(Hoverable):
    def __init__(self, item: dict, opener=None, parent=None):
        super().__init__(parent)
        self.item = item
        self.opener = opener
        self.path = expand(item.get("path", ""))
        icon_spec = item.get("icon", "")
        self.pm = None
        if str(icon_spec).startswith("appx:"):
            resolve_appx(icon_spec, self._set_icon)
        else:
            self.pm = file_icon(expand(icon_spec) or self.path)
        self.setFixedSize(44, 44)
        self.setToolTip(item.get("name", os.path.basename(self.path)))
        self.clicked.connect(self.run)

    def _set_icon(self, path):
        self.pm = file_icon(path)
        self.update()

    def run(self):
        args = self.item.get("args") or []
        if isinstance(args, str):
            args = args.split()
        if self.opener is not None:
            self.opener(self.path, self.item.get("exe"), args)
        else:
            launch(self.path, args)

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        s = self.press_scale() * (1 + 0.06 * self._hover.x)
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        if self._hover.x > 0.01:
            c = theme.hover()
            c.setAlphaF(c.alphaF() * self._hover.x)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 12, 12)
        if self.pm is not None:
            ir = QtCore.QRectF(r.center().x() - 14, r.center().y() - 14, 28, 28)
            p.drawPixmap(ir.toRect(), self.pm)
        else:
            p.setFont(ui_font(15, W.Bold))
            p.setPen(theme.text(0.8))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, (self.item.get("name") or "?")[:1])


class PetWidget(QtWidgets.QWidget):
    """主页中间随机显示三月七贴纸；定时和点击都会切换。"""
    def __init__(self, parent=None, scale: float = 2.3):
        super().__init__(parent)
        self.paths = sticker_paths()
        self.cache: dict[str, QtGui.QPixmap] = {}
        self.current = -1
        self.pm: QtGui.QPixmap | None = None
        self.setMinimumWidth(round(82 * scale))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = QtCore.QTimer(self, singleShot=True, timeout=self._pick)
        self._motion = QtCore.QTimer(self, interval=16, timeout=self._motion_tick)
        self._motion.setTimerType(Qt.TimerType.PreciseTimer)
        self._dx = Spring(0, 180, 0.72, 0.01)
        self._dy = Spring(0, 180, 0.72, 0.01)
        self._rot = Spring(0, 150, 0.78, 0.01)
        self._pick()

    def _load(self, path) -> QtGui.QPixmap | None:
        key = str(path)
        if key in self.cache:
            return self.cache[key]
        pm = load_sticker(path, 300)
        if pm is None:
            return None
        if len(self.cache) >= 8:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = pm
        return pm

    def reload_stickers(self):
        self.paths = sticker_paths()
        self.cache.clear()
        self.current = -1
        self._pick()

    def react(self, _kind: str = "surprise"):
        self._pick()

    def _pick(self):
        latest = sticker_paths()
        if latest != self.paths:
            self.paths = latest
            self.cache.clear()
            self.current = -1
        if not self.paths:
            self.pm = None
            self.update()
            return
        choices = [i for i in range(len(self.paths)) if i != self.current]
        self.current = random.choice(choices or [0])
        self.pm = self._load(self.paths[self.current])
        self.update()
        if self.isVisible():
            self._t.start(random.randint(7000, 13000))

    def _motion_tick(self):
        c = QtCore.QPointF(self.rect().center())
        pos = QtCore.QPointF(self.mapFromGlobal(QtGui.QCursor.pos()))
        nx = clamp((pos.x() - c.x()) / max(1.0, self.width() / 2), -1.0, 1.0)
        ny = clamp((pos.y() - c.y()) / max(1.0, self.height() / 2), -1.0, 1.0)
        self._dx.to(nx * 9.0)
        self._dy.to(ny * 6.0)
        self._rot.to(nx * 2.4)
        self._dx.step(0.016)
        self._dy.step(0.016)
        self._rot.step(0.016)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._t.isActive():
            self._t.start(random.randint(7000, 13000))
        self._motion.start()

    def hideEvent(self, e):
        self._t.stop()
        self._motion.stop()
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pressed = getattr(self, "_pressed", False)
            self._pressed = False
            if pressed and self.rect().contains(e.position().toPoint()):
                self._pick()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        if self.pm is None:
            return
        p = painter(self)
        target = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        size = self.pm.size()
        size.scale(target.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        r = QtCore.QRectF(0, 0, size.width(), size.height())
        r.moveCenter(target.center() + QtCore.QPointF(self._dx.x, self._dy.x))
        p.translate(r.center())
        p.rotate(self._rot.x)
        p.translate(-r.center())
        p.drawPixmap(r.toRect(), self.pm)


class LaunchStrip(QtWidgets.QScrollArea):
    """启动器横条：应用多到放不下时，滚轮横向平滑滚动（不显示滚动条）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setFixedHeight(46)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}")
        self.viewport().setStyleSheet("background:transparent")
        self.inner = QtWidgets.QWidget()
        self.inner.setObjectName("stripInner")
        self.inner.setStyleSheet("#stripInner{background:transparent}")
        self.setWidget(self.inner)
        self.inner.setAutoFillBackground(False)
        self.row = QtWidgets.QHBoxLayout(self.inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self._anim = QtCore.QPropertyAnimation(self.horizontalScrollBar(), b"value", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        if bar.maximum() <= 0:
            e.ignore()
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        start = self._anim.endValue() if self._anim.state() == QtCore.QAbstractAnimation.State.Running else bar.value()
        target = max(0, min(bar.maximum(), int(start) - d))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()
        e.accept()


class HomePage(Page):
    key, glyph, title, height = "home", G.HOME, "主页", 264

    def __init__(self, ctx):
        super().__init__(ctx)
        self.media = MediaCard(ctx)
        self.media.setFixedHeight(210)
        self.a_pin = Action(G.UNPIN, "保持展开")
        self.a_pt = Action(G.POINTER, "可穿透")
        self.a_mute = Action(G.IMAGE, "参与截图")
        self.a_live = Action(G.MONITOR, "全屏显示")
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(8)
        grid.addWidget(self.a_pin, 0, 0)
        grid.addWidget(self.a_pt, 0, 1)
        grid.addWidget(self.a_mute, 1, 0)
        grid.addWidget(self.a_live, 1, 1)
        gw = QtWidgets.QWidget()
        gw.setLayout(grid)
        gw.setFixedWidth(150)
        self.strip = LaunchStrip()
        self.launch_row = self.strip.row
        self.build_launcher()
        self.pet = PetWidget()
        # 播放卡贴左、四个按钮贴右，各自收窄；中间整块留给小形象
        self.media.setFixedWidth(200)
        lay = vbox(hbox(self.media, (self.pet, 1), gw, spacing=12), self.strip, spacing=8)
        self.setLayout(lay)

    def build_launcher(self):
        while self.launch_row.count():
            it = self.launch_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        enabled = bool(cfg.get("launcher_enabled", True))
        self.strip.setVisible(enabled)
        # 210px 主区 + 8px 间距 + 46px 快速应用栏；不再额外保留空白。
        self.set_height(264 if enabled else 210)
        if enabled:
            for item in cfg.get("launcher") or []:
                self.launch_row.addWidget(LaunchIcon(item, self._open))
            self.launch_row.addStretch(1)

    def _open(self, path, exe=None, args=None):
        res = self.ctx.windows.open_or_focus(path, exe, args)
        if res == "focused" and self.island:
            self.island.collapse()

    def set_capture_visible(self, on: bool):
        self.a_mute.set_on(on, G.IMAGE, "参与截图" if on else "不参与截图")

    def set_fullscreen_visible(self, on: bool):
        self.a_live.set_on(on, G.MONITOR, "全屏显示" if on else "全屏隐藏")


def cfg_path():
    from ...core.config import CONFIG_PATH
    return CONFIG_PATH


# ======================================================================== 消息
class AppTile(Hoverable):
    def __init__(self, kind: str, name: str, glyph: str, parent=None):
        super().__init__(parent)
        self.kind, self.name, self.glyph = kind, name, glyph
        self.count = 0
        self.last = ""
        self.setFixedHeight(84)

    def set_count(self, n: int, last: str = ""):
        self.count, self.last = n, last
        self.update()

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        s = self.press_scale()
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.card(1.0 + 0.6 * self._hover.x))
        p.drawRoundedRect(r, 18, 18)
        col = KIND_COLORS.get(self.kind, KIND_COLORS["other"])
        cr = QtCore.QRectF(r.x() + 12, r.y() + 12, 30, 30)
        p.setBrush(col)
        p.drawEllipse(cr)
        p.setFont(icon_font(14))
        p.setPen(QtGui.QColor("white"))
        p.drawText(cr, Qt.AlignmentFlag.AlignCenter, self.glyph)
        p.setFont(ui_font(13, W.DemiBold))
        p.setPen(theme.text())
        p.drawText(QtCore.QRectF(cr.right() + 8, cr.y(), 120, 30), Qt.AlignmentFlag.AlignVCenter, self.name)
        p.setFont(ui_font(22, W.Bold, num=True))
        p.setPen(col if self.count else theme.text3())
        p.drawText(QtCore.QRectF(r.x() + 14, r.y() + 46, r.width() - 28, 30), Qt.AlignmentFlag.AlignVCenter,
                   str(self.count) if self.count else "0")
        p.setFont(ui_font(11))
        p.setPen(theme.text3())
        p.drawText(QtCore.QRectF(r.x() + 14, r.y() + 46, r.width() - 26, 30),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   self.last or "")


class HistoryList(QtWidgets.QWidget, Themed):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []
        self._hook_theme()

    def set_rows(self, rows):
        self.rows = rows[:30]
        self.setFixedHeight(max(30, len(self.rows) * 30))
        self.update()

    def paintEvent(self, e):
        p = painter(self)
        if not self.rows:
            p.setFont(ui_font(12))
            p.setPen(theme.text3())
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无")
            return
        for i, r in enumerate(self.rows):
            y = i * 30
            col = KIND_COLORS.get(r.get("kind"), KIND_COLORS["other"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QtCore.QPointF(10, y + 15), 4, 4)
            p.setFont(ui_font(12.5, W.Medium))
            p.setPen(theme.text())
            p.drawText(QtCore.QRectF(24, y, 80, 30), Qt.AlignmentFlag.AlignVCenter, r.get("name", ""))
            kind = r.get("kind")
            desc = "新邮件" if kind == "mail" else (f"{r['sender']} 发来消息" if r.get("sender") else "新消息")
            p.setFont(ui_font(12.5))
            p.setPen(theme.text2())
            p.drawText(QtCore.QRectF(100, y, self.width() - 170, 30), Qt.AlignmentFlag.AlignVCenter,
                       QtGui.QFontMetrics(p.font()).elidedText(desc, Qt.TextElideMode.ElideRight, self.width() - 170))
            p.setFont(ui_font(11.5, num=True))
            p.setPen(theme.text3())
            p.drawText(QtCore.QRectF(self.width() - 64, y, 60, 30), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       time.strftime("%H:%M", time.localtime(r.get("time", 0))))


class MessagesPage(Page):
    key, glyph, title, height = "msg", G.MESSAGE, "消息", 270
    TILE_H, HEAD_H, ROW_H, GAP, MAX_H = 84, 26, 30, 8, 270   # 卡片 / 按钮行 / 记录 / 间距 / 最高

    def __init__(self, ctx):
        super().__init__(ctx)
        self.tiles = {
            "qq": AppTile("qq", "QQ", G.CHAT),
            "wechat": AppTile("wechat", "微信", G.MESSAGE),
            "mail": AppTile("mail", "邮件", G.MAIL),
        }
        for k, t in self.tiles.items():
            t.clicked.connect(lambda k=k: self._open(k))
        self.hist = HistoryList()
        self.sc = ScrollArea()
        # ScrollArea 默认最小高度 50，会把整页最小高度顶到 176；这里改成一条记录的高度，
        # 让页面最小高度与 refresh() 算出的高度保持一致，布局才不会被纵向压缩。
        self.sc.setMinimumHeight(self.ROW_H)
        lay = QtWidgets.QVBoxLayout(self.sc.inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.hist)
        lay.addStretch(1)
        clear = PillButton("全部已读", G.CHECK, height=26)
        clear.clicked.connect(self._clear_all)
        self.head = QtWidgets.QWidget()
        self.head.setLayout(hbox(None, clear))
        self.setLayout(vbox(hbox(*self.tiles.values(), spacing=8), self.head, (self.sc, 1), spacing=8))

    def _open(self, kind):
        self.ctx.notify.open(kind)
        if self.island:
            self.island.collapse()

    def _clear_all(self):
        for k in list(self.ctx.notify.counts):
            self.ctx.notify.clear(k)

    def refresh(self):
        counts = self.ctx.notify.counts
        hist = list(self.ctx.notify.history)
        for k, t in self.tiles.items():
            last = next((h for h in hist if h.get("kind") == k), None)
            t.set_count(counts.get(k, 0), time.strftime("%H:%M", time.localtime(last["time"])) if last else "")
        self.hist.set_rows(hist)
        has_hist = bool(hist)
        self.head.setVisible(has_hist)
        self.sc.setVisible(has_hist)
        if not has_hist:
            self.set_height(self.TILE_H)
        else:
            base = self.TILE_H + self.GAP + self.HEAD_H + self.GAP    # 卡片 + 按钮行
            rows = min(len(hist), 5)                                   # 最多展示 5 条，其余滚动
            self.set_height(min(self.MAX_H, base + rows * self.ROW_H))

    def on_show(self):
        super().on_show()
        self.refresh()
