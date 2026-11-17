# -*- coding: utf-8 -*-
"""控制中心（音量 / 亮度 / WLAN / 蓝牙 / 移动热点 / 声音输出 / Clash Verge）、窗口切换、性能监控。"""
from __future__ import annotations

import re

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.bg import run_bg
from ...core.config import cfg
from ..anim import clamp
from ..theme import G, W, icon_font, theme, ui_font
from ..widgets import (Card, Hoverable, IconButton, Label, PillButton, ScrollArea, Segmented, Slider, Sparkline,
                       Themed, Tile, TogglePill, fmt_bytes, hbox, painter, vbox)
from .base import Page

Qt = QtCore.Qt
MODES = [("rule", "规则"), ("global", "全局"), ("direct", "直连")]


def short_device(name: str) -> str:
    """'扬声器 (2- Realtek(R) Audio)' -> '扬声器'（磁贴上只留设备本身的名字）。"""
    s = re.sub(r"\s*[\(（][^\(）]*[\)）]\s*$", "", str(name or "")).strip()
    return s or str(name or "")


def short_node(name: str) -> str:
    """"JMS-1411881@c51s2.xxx:443" -> "c51s2"（@ 后面 5 个字符）。"""
    if "@" in name:
        return name.split("@", 1)[1][:5]
    return name


def _close_on_outside_click(m: QtWidgets.QMenu):
    """灵动岛不抢焦点，Qt 的"点外面关闭菜单"不会触发；这里轮询鼠标键，点到菜单外就关闭。"""
    import ctypes
    u32 = ctypes.WinDLL("user32")
    st = {"armed": False}
    t = QtCore.QTimer(m)
    t.setInterval(25)

    def down() -> bool:
        return any(u32.GetAsyncKeyState(k) & 0x8000 for k in (0x01, 0x02, 0x04))

    def tick():
        if not m.isVisible():
            t.stop()
            return
        if not st["armed"]:
            st["armed"] = not down()          # 先等打开菜单的那次按键松开
            return
        if down():
            pos = QtGui.QCursor.pos()
            menus = [w for w in QtWidgets.QApplication.topLevelWidgets()
                     if isinstance(w, QtWidgets.QMenu) and w.isVisible()]
            if not any(w.geometry().contains(pos) for w in menus):
                m.close()
                t.stop()
    t.timeout.connect(tick)
    m.aboutToShow.connect(lambda: (st.update(armed=False), t.start()))
    m.aboutToHide.connect(t.stop)


def styled_menu(parent=None) -> QtWidgets.QMenu:
    m = QtWidgets.QMenu(parent)
    _close_on_outside_click(m)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    m.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    m.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
    bg, fg, sel = theme.menu_qss()
    m.setStyleSheet(
        f"QMenu{{background:{bg};border-radius:14px;padding:6px;color:{fg};font-family:'HarmonyOS Sans','Microsoft YaHei UI';font-size:13px}}"
        f"QMenu::item{{padding:6px 22px 6px 14px;border-radius:9px}}"
        f"QMenu::item:selected{{background:{sel}}}"
        f"QMenu::item:disabled{{color:gray}}"
        "QMenu::separator{height:6px;background:transparent}"
        "QMenu::indicator{width:0}")
    return m


class AppAudioIcon(Hoverable):
    """音量合成器里的应用图标；点击切换该应用静音。"""
    toggled = QtCore.Signal(bool)      # 立刻把新状态同步给同行滑块，不必等下一次轮询

    def __init__(self, ctx, info: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.info = dict(info)
        self.pm = None
        self.setFixedSize(38, 38)
        self.setToolTip("点击静音 / 取消静音")
        self.clicked.connect(self._toggle)
        self._load_icon()

    def _load_icon(self):
        img = self.ctx.windows.exe_icon(self.info.get("exe") or "")
        self.pm = QtGui.QPixmap.fromImage(img) if isinstance(img, QtGui.QImage) and not img.isNull() else None

    def set_info(self, info: dict):
        old_exe = self.info.get("exe")
        self.info = dict(info)
        if old_exe != self.info.get("exe"):
            self._load_icon()
        self.update()

    def _toggle(self):
        muted = not bool(self.info.get("muted"))
        self.info["muted"] = muted
        self.ctx.audio.set_session_muted(self.info["key"], muted)
        self.toggled.emit(muted)
        self.update()

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self._hover.x > 0.01:
            c = theme.hover()
            c.setAlphaF(c.alphaF() * self._hover.x)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(r)
        p.setOpacity(0.38 if self.info.get("muted") else 1.0)
        if self.pm is not None:
            p.drawPixmap(r.adjusted(5, 5, -5, -5).toRect(), self.pm)
        else:
            p.setFont(icon_font(17))
            p.setPen(theme.text(0.9))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, G.VOLUME if self.info.get("system") else G.APPS)
        p.setOpacity(1.0)
        if self.info.get("muted"):
            p.setFont(icon_font(11))
            p.setPen(QtGui.QColor("#ef4444"))
            p.drawText(QtCore.QRectF(r.right() - 14, r.bottom() - 14, 14, 14), Qt.AlignmentFlag.AlignCenter, G.MUTE)


class AppVolumeRow(QtWidgets.QWidget):
    def __init__(self, ctx, info: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.info = dict(info)
        self.icon = AppAudioIcon(ctx, info)
        self.icon.toggled.connect(self.set_muted)
        self.name = Label(info.get("name") or "未知应用", 11.5, W.Medium)
        self.name.setFixedWidth(82)
        self.slider = Slider("", height=30)
        self.slider.moved.connect(lambda v: self.ctx.audio.set_session_volume(self.info["key"], v))
        self.setLayout(hbox(self.icon, self.name, (self.slider, 1), spacing=8, margins=(2, 2, 6, 2)))
        self.setFixedHeight(44)
        self.set_info(info)

    def set_info(self, info: dict):
        self.info = dict(info)
        self.icon.set_info(info)
        self.name.setText(info.get("name") or "未知应用")
        self.name.setToolTip(info.get("exe") or self.name.text())
        self.set_muted(bool(info.get("muted")))
        self.slider.set_value(float(info.get("volume") or 0), animate=False)

    def set_muted(self, muted: bool):
        self.slider.label = "静音" if muted else ""
        self.slider.set_muted(bool(muted))   # 静音时填充收空，值仍保留，取消静音后填回
        self.slider.update()


class AppMixer(Card):
    """最多显示三项的应用音量合成器，更多应用在内部滚动。"""
    def __init__(self, ctx, parent=None):
        super().__init__(parent, 16)
        self.ctx = ctx
        self.rows: dict[str, AppVolumeRow] = {}
        self.title = Label("音量合成器", 12.5, W.DemiBold)
        self.hint = Label("点击应用图标静音", 10.5, level=3)
        self.scroll = ScrollArea()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFixedHeight(142)       # 3 × 44px 行高 + 2 × 5px 间距
        self.setFixedWidth(270)
        self.rows_lay = QtWidgets.QVBoxLayout(self.scroll.inner)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(5)
        self.empty = Label("暂无正在使用声音的应用", 11.5, level=3)
        self.rows_lay.addWidget(self.empty)
        self.rows_lay.addStretch(1)
        self.setLayout(vbox(hbox(self.title, None, self.hint), self.scroll, spacing=5, margins=(12, 8, 8, 8)))

    def set_sessions(self, sessions: list[dict]):
        keys = [str(x.get("key")) for x in sessions]
        for key in list(self.rows):
            if key not in keys:
                self.rows.pop(key).deleteLater()
        self.empty.setVisible(not sessions)
        for info in sessions:
            key = str(info.get("key"))
            row = self.rows.get(key)
            if row is None:
                row = AppVolumeRow(self.ctx, info)
                self.rows[key] = row
            else:
                row.set_info(info)
        while self.rows_lay.count():
            self.rows_lay.takeAt(0)
        for info in sessions:
            self.rows_lay.addWidget(self.rows[str(info.get("key"))])
        if not sessions:
            self.rows_lay.addWidget(self.empty)
        self.rows_lay.addStretch(1)
        rows_h = len(sessions) * 44 + max(0, len(sessions) - 1) * 5
        self.scroll.inner.setMinimumHeight(max(142, rows_h))


class ControlsPage(Page):
    key, glyph, title, height = "ctl", G.SLIDERS, "控制", 301

    def __init__(self, ctx):
        super().__init__(ctx)
        self._radio = {}
        self._clash = {}
        self._hs = {}
        self._clash_ok = False
        self._audio_dev = None

        self.vol = Slider(G.VOLUME)
        self.bri = Slider(G.SUN)
        self.vol.moved.connect(self._set_vol)
        self.vol.icon_clicked.connect(lambda: ctx.audio.toggle_mute())
        self.bri.moved.connect(lambda v: ctx.brightness.set(None, round(v * 100)))

        # ---- 右侧磁贴：WLAN / 蓝牙 / 移动热点 / 声音输出 ----
        self.wifi = Tile(G.WIFI, "WLAN")
        self.bt = Tile(G.BT, "蓝牙")
        self.hs = Tile(G.HOTSPOT, "移动热点")
        self.audio = Tile(G.HEADPHONE, "声音输出")
        self.hs.set_state(False, "已关闭")
        self.audio.set_state(True, "—")
        self.wifi.clicked.connect(lambda: self._toggle("wifi"))
        self.bt.clicked.connect(lambda: self._toggle("bt"))
        self.hs.clicked.connect(self._toggle_hotspot)
        self.audio.clicked.connect(self._audio_menu)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.gw = QtWidgets.QWidget()
        self.gw.setLayout(self.grid)
        self.gw.setFixedWidth(270)

        # ---- Clash 卡片（模式 / 节点 / 系统代理 / TUN 都在这里）----
        self.card = Card(radius=18)
        self.mode = Segmented([n for _, n in MODES], height=32)
        self.mode.setMinimumWidth(250)
        self.mode.changed.connect(lambda i: ctx.clash.set_mode(MODES[i][0]))
        self.node = PillButton("节点", G.GLOBE, height=32)
        self.node.clicked.connect(self._node_menu)
        self.node.setMaximumWidth(320)
        self.speed = Label("", 11.5, level=2, num=True)
        self.clash_state = Label("Clash Verge", 13, W.DemiBold)
        self.open_btn = IconButton(G.OPEN, 28, 12, "打开 / 唤出 Clash Verge")
        self.open_btn.clicked.connect(lambda: ctx.clash.open_app())
        self.sys_proxy = TogglePill(G.GLOBE, "系统代理")
        self.sys_tun = TogglePill(G.BOLT, "TUN")
        self.sys_proxy.clicked.connect(self._toggle_sysproxy)
        self.sys_tun.clicked.connect(self._toggle_tun)
        self.card.setFixedHeight(217)
        self.card.setLayout(vbox(
            hbox(self.clash_state, None, self.speed, self.open_btn, spacing=8),
            self.mode,
            self.node,
            hbox(self.sys_proxy, self.sys_tun, None, spacing=10),
            spacing=12, margins=(14, 12, 14, 12)))

        left = vbox(self.vol, self.bri, self.card, spacing=8)
        self.card.hide()
        self.mixer = AppMixer(ctx)
        ctx.audio.sessions_changed.connect(self.mixer.set_sessions)
        # 音量合成器放在 WLAN / 蓝牙 / 热点 / 输出设备这一列，不再横跨整页。
        right = vbox(self.gw, self.mixer, spacing=8)
        self.setLayout(hbox((left, 1), right, spacing=10))
        self.apply_visibility()
        self.set_audio_devices()
        self._refresh_audio()          # 启动时先在后台把设备列表备好，打开这一页就不用等

    # ---------------- 显示哪些磁贴 ----------------
    def apply_visibility(self):
        """按 config.json → controls 里的开关显示 / 隐藏磁贴与滑块（设置页面里可改）。"""
        tiles = cfg.get("controls.tiles") or {}
        shown = []
        for key, w in (("wifi", self.wifi), ("bt", self.bt), ("hotspot", self.hs), ("audio", self.audio)):
            on = bool(tiles.get(key, True))
            w.setVisible(on)
            if on:
                shown.append(w)
        while self.grid.count():
            self.grid.removeWidget(self.grid.itemAt(0).widget())
        for i, w in enumerate(shown):
            self.grid.addWidget(w, i // 2, i % 2)
        for c in range(2):
            self.grid.setColumnStretch(c, 1)
        self.gw.setVisible(bool(shown))
        self.vol.setVisible(bool(cfg.get("controls.show_volume", True)))
        self.bri.setVisible(bool(cfg.get("controls.show_brightness", True)))
        self.card.setVisible(bool(cfg.get("controls.show_clash", True)) and self._clash_ok)
        show_mixer = bool(cfg.get("controls.show_mixer", True))
        self.mixer.setVisible(show_mixer)
        self.set_height(301 if show_mixer else 208)
        if not show_mixer:
            self.ctx.audio.set_session_polling(False)

    def _toggle(self, kind: str):
        """可用就切换开关；检测不到（台式机没蓝牙 / 驱动不支持）时打开对应的系统设置页。"""
        import os
        if not self._radio.get(f"{kind}_available", False):
            os.startfile("ms-settings:" + ("bluetooth" if kind == "bt" else "network-wifi"))  # noqa: S606
            if self.island:
                self.island.collapse()
            return
        if kind == "bt":
            self.ctx.radio.set_bluetooth(not self._radio.get("bt_on"))
        else:
            self.ctx.radio.set_wifi(not self._radio.get("wifi_on"))

    def _toggle_hotspot(self):
        import os
        if not self._hs.get("available", False):
            os.startfile("ms-settings:network-mobilehotspot")  # noqa: S606
            if self.island:
                self.island.collapse()
            return
        self.ctx.hotspot.toggle()

    def _set_vol(self, v: float):
        a = self.ctx.audio
        a.set_volume(v)
        if v > 0.001 and a.muted():
            a.set_muted(False)          # 调大音量时顺便取消静音（否则看起来"没反应"）

    # ---------------- 声音输出设备 ----------------
    def set_audio_devices(self, devs=None):
        """渲染「声音输出」磁贴。devs 为空时读缓存——枚举播放设备要走十几次 COM，
        在主线程做会把打开页面卡一下，所以枚举统一放后台（AudioService.warm_output）。"""
        if devs is None:
            devs = self.ctx.audio.output_devices(cached=True)
        dev = next((d for d in devs if d["default"]), None) or (devs[0] if devs else None)
        self._audio_dev = dev
        if dev is None:
            self.audio.set_state(True, "—", False)
            self.audio.setToolTip("正在读取播放设备…")
        else:
            self.audio.set_state(True, dev["name"], True)
            self.audio.setToolTip(f"当前输出：{dev.get('full_name') or dev['name']}\n点击切换播放设备")

    def _refresh_audio(self):
        self.ctx.audio.warm_output(self.set_audio_devices)

    def _audio_menu(self):
        devs = self.ctx.audio.output_devices(cached=True) or self.ctx.audio.output_devices()
        if not devs:
            return
        m = styled_menu(self)
        for d in devs:
            name = d.get("full_name") or d.get("name") or "未命名设备"
            a = m.addAction(("✓  " if d["default"] else "    ") + name)
            a.setToolTip(name)
            a.triggered.connect(lambda _=False, i=d["id"]: self._use_audio(i))
        if self.island:
            self.island.locks.add("menu")
            m.aboutToHide.connect(lambda: self.island.locks.discard("menu"))
        m.popup(QtGui.QCursor.pos())

    def _use_audio(self, dev_id: str):
        self.ctx.audio.set_default_output(dev_id)
        QtCore.QTimer.singleShot(250, self._refresh_audio)

    # ---------------- 数据 ----------------
    def set_volume(self, v: float, muted: bool):
        self.vol.glyph = G.MUTE if muted else (G.VOLUME_LOW if v < 0.34 else G.VOLUME)
        self.vol.label = "静音" if muted else ""
        self.vol.set_value(v)
        self.vol.set_muted(muted)      # 静音时填充收空，值仍保留 80，取消静音后自动填回

    def set_brightness(self, mons: list):
        if not mons:
            self.bri.label = "不支持"
            self.bri.update()
            return
        vals = [m.get("brightness") for m in mons if m.get("brightness") is not None]
        if vals:
            self.bri.label = ""
            self.bri.set_value(sum(vals) / len(vals) / 100)

    def set_radio(self, d: dict):
        self._radio = d
        self.wifi.set_state(bool(d.get("wifi_on")),
                            (d.get("wifi_ssid") or ("已开启" if d.get("wifi_on") else "已关闭"))
                            + (f" · {d['wifi_signal']}%" if d.get("wifi_signal") and d.get("wifi_ssid") else ""),
                            d.get("wifi_available", True))
        bt_ok = d.get("bt_available", True)
        self.bt.set_state(bool(d.get("bt_on")),
                          ("已开启" if d.get("bt_on") else "已关闭") if bt_ok else "未检测到 · 点击打开设置", bt_ok)
        self.wifi.setToolTip(("已连接：" + d["wifi_ssid"]) if d.get("wifi_ssid") else "WLAN")
        self.bt.setToolTip("蓝牙" if bt_ok else "这台电脑没有可切换的蓝牙适配器，点击打开系统设置")

    def set_hotspot(self, d: dict):
        self._hs = d
        ok = bool(d.get("available"))
        on = bool(d.get("on"))
        if not ok:
            self.hs.set_state(False, d.get("reason") or "不可用 · 点击打开设置", False)
            self.hs.setToolTip(d.get("reason") or "移动热点不可用，点击打开系统设置")
            return
        sub = ("已开启" if on else "已关闭")
        if on and d.get("ssid"):
            sub = f"{d['ssid']}"
        if on and d.get("clients"):
            sub += f" · {d['clients']} 台"
        self.hs.set_state(on, sub, True)
        self.hs.setToolTip(f"移动热点：{'已开启' if on else '已关闭'}"
                           + (f"\n名称 {d.get('ssid')}，{d.get('clients', 0)} 台设备" if on else ""))

    def _toggle_sysproxy(self):
        """点一下立刻变色（乐观更新），后台写完再由下一次轮询校准。
        不然 1 秒的轮询间隔里用户看不到反应，很容易再点一下又给关回去。"""
        want = not bool(self._clash.get("sysproxy"))
        self._clash["sysproxy"] = want
        self.sys_proxy.set_on(want, "系统代理", True)
        self.ctx.clash.set_sysproxy(want)

    def _toggle_tun(self):
        want = not bool(self._clash.get("tun"))
        self._clash["tun"] = want
        self.sys_tun.set_on(want, "TUN", True)
        self.ctx.clash.set_tun(want)

    def set_clash(self, d: dict):
        self._clash = d
        ok = bool(d.get("ok"))
        self._clash_ok = ok
        # 只有检测到 Clash Verge 在运行时才显示卡片（没装的用户看不到无用的面板）
        self.card.setVisible(ok and bool(cfg.get("controls.show_clash", True)))
        self.sys_proxy.set_on(bool(d.get("sysproxy")), "系统代理", bool(ok))
        self.sys_tun.set_on(bool(d.get("tun")), "TUN", bool(ok))
        if ok:
            self.clash_state.setText("Clash Verge")
            self.speed.setText(f"↑ {fmt_bytes(d.get('up', 0), True)}   ↓ {fmt_bytes(d.get('down', 0), True)}")
            keys = [k for k, _ in MODES]
            if d.get("mode") in keys:
                self.mode.set_index(keys.index(d["mode"]))
            delay = d.get("delay")
            node = short_node(d.get("node") or "—")
            self.node.set_text(f"{node}" + (f"  {delay}ms" if delay else ""))
        else:
            self.clash_state.setText("Clash 未运行")
            self.speed.setText(d.get("error") or "")
            self.node.set_text("—")

    def _node_menu(self):
        d = self._clash
        nodes = d.get("nodes") or []
        if not nodes:
            return
        m = styled_menu(self)
        group = d.get("group")
        for n in nodes[:60]:
            a = m.addAction(("✓  " if n == d.get("node") else "    ") + short_node(n) + ("" if "@" not in n else f"    {n.split('@')[0]}"))
            a.triggered.connect(lambda _=False, n=n: self.ctx.clash.select(group, n))
        m.addSeparator()
        t = m.addAction("    测试当前节点延迟")
        t.triggered.connect(lambda: self.ctx.clash.test_delay(d.get("node"), lambda ms: self.node.set_text(
            f"{short_node(d.get('node') or '')}  {ms}ms" if ms else f"{short_node(d.get('node') or '')}  超时")))
        if self.island:
            self.island.locks.add("menu")
            m.aboutToHide.connect(lambda: self.island.locks.discard("menu"))
        m.popup(QtGui.QCursor.pos())

    def on_show(self):
        super().on_show()
        self.ctx.brightness.refresh()
        self.ctx.radio.refresh()
        self.ctx.clash.set_detail_polling(True)
        hs = getattr(self.ctx, "hotspot", None)
        if hs is not None:
            hs.set_detail_polling(True)
        # 先用缓存立刻铺上（打开这一页不能卡），设备枚举丢后台，回来再更新
        self.set_audio_devices()
        self._refresh_audio()
        if cfg.get("controls.show_mixer", True):
            self.mixer.set_sessions(self.ctx.audio.audio_sessions())
            self.ctx.audio.set_session_polling(True)

    def on_hide(self):
        self.ctx.audio.set_session_polling(False)
        self.ctx.clash.set_detail_polling(False)
        hs = getattr(self.ctx, "hotspot", None)
        if hs is not None:
            hs.set_detail_polling(False)
        super().on_hide()


# ======================================================================== 窗口切换
class WinCard(Hoverable):
    closed = QtCore.Signal()

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        img = info.get("icon")
        self.pm = QtGui.QPixmap.fromImage(img) if isinstance(img, QtGui.QImage) and not img.isNull() else None
        self.setFixedHeight(54)
        self.setToolTip(f"{info.get('title')}\n{info.get('exe')}")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton or (
                e.button() == Qt.MouseButton.LeftButton and self._close_rect().contains(e.position())):
            self.closed.emit()
            return
        super().mouseReleaseEvent(e)

    def _close_rect(self):
        return QtCore.QRectF(self.width() - 26, 6, 20, 20)

    def paintEvent(self, e):
        p = painter(self)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        s = self.press_scale()
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.card(1.0 + 0.7 * self._hover.x) if not self.info.get("active") else theme.active_pill())
        p.drawRoundedRect(r, 14, 14)
        ir = QtCore.QRectF(r.x() + 10, r.center().y() - 14, 28, 28)
        if self.pm is not None:
            p.drawPixmap(ir.toRect(), self.pm)
        else:
            p.setFont(icon_font(18))
            p.setPen(theme.text(0.8))
            p.drawText(ir, Qt.AlignmentFlag.AlignCenter, G.APPS)
        tx = ir.right() + 9
        tw = r.right() - tx - (26 if self._hover.x > 0.3 else 8)
        p.setFont(ui_font(12.5, W.Medium))
        p.setPen(theme.text())
        fm = QtGui.QFontMetrics(p.font())
        p.drawText(QtCore.QRectF(tx, r.y() + 8, tw, 20), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.info.get("title", ""), Qt.TextElideMode.ElideRight, int(tw)))
        p.setFont(ui_font(10.5))
        p.setPen(theme.text3())
        p.drawText(QtCore.QRectF(tx, r.y() + 27, tw, 18), Qt.AlignmentFlag.AlignVCenter,
                   (self.info.get("exe") or "").removesuffix(".exe"))
        if self._hover.x > 0.05:
            cr = self._close_rect()
            c = theme.text(0.55 * self._hover.x)
            p.setFont(icon_font(10))
            p.setPen(c)
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, G.CLOSE)


class TasksPage(Page):
    key, glyph, title, height = "tasks", G.WINDOWS, "窗口", 300

    def __init__(self, ctx):
        super().__init__(ctx)
        self.sc = ScrollArea()
        self.grid = QtWidgets.QGridLayout(self.sc.inner)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(8)
        self.count = Label("", 12, level=3)
        self.setLayout(vbox(hbox(Label("点击切换 · 中键或 × 关闭", 12, level=2), None, self.count), (self.sc, 1), spacing=8))
        self.timer = QtCore.QTimer(self, interval=2000, timeout=self.refresh)
        self._sig = None

    def refresh(self):
        wins = self.ctx.windows.list_windows()
        sig = tuple((w["hwnd"], w["title"], w.get("active")) for w in wins)
        if sig == self._sig:
            return
        self._sig = sig
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cols = 3
        for i, w in enumerate(wins):
            c = WinCard(w)
            c.clicked.connect(lambda h=w["hwnd"]: self._activate(h))
            c.closed.connect(lambda h=w["hwnd"]: self._close(h))
            self.grid.addWidget(c, i // cols, i % cols)
        for k in range(cols):
            self.grid.setColumnStretch(k, 1)
        self.grid.setRowStretch(len(wins) // cols + 1, 1)
        self.count.setText(f"{len(wins)} 个窗口")
        rows = (len(wins) + cols - 1) // cols
        self.set_height(int(clamp(30 + rows * 62, 120, 330)))

    def _activate(self, hwnd):
        if self.island:
            self.island.collapse()
        QtCore.QTimer.singleShot(60, lambda: self.ctx.windows.activate(hwnd))

    def _close(self, hwnd):
        self.ctx.windows.close(hwnd)
        QtCore.QTimer.singleShot(400, self.refresh)

    def on_show(self):
        super().on_show()
        self._sig = None
        self.refresh()
        self.timer.start()

    def on_hide(self):
        super().on_hide()
        self.timer.stop()


# ======================================================================== 性能
class Meter(Card):
    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent, 18)
        self.t = Label(title, 12, W.DemiBold, level=2)
        self.v = Label("--", 22, W.DemiBold, num=True)
        self.v.setFixedHeight(30)
        self.sub = Label("", 10.5, level=3)
        self.spark = Sparkline(color=QtGui.QColor(color), fixed_max=100)
        self.spark.setFixedHeight(40)
        self.setLayout(vbox(hbox(self.t, None, self.sub), self.v, self.spark, spacing=0, margins=(12, 8, 12, 8)))


class PerfPage(Page):
    key, glyph, title, height = "perf", G.PULSE, "性能", 296

    def __init__(self, ctx):
        super().__init__(ctx)
        self.cpu = Meter("CPU", "#4f8cff")
        self.gpu = Meter("GPU", "#bf5af2")
        self.mem = Meter("内存", "#30d158")
        self.net = Card(radius=18)
        self.net_up = Label("", 12, W.Medium, num=True)
        self.net_dn = Label("", 12, W.Medium, num=True)
        self.disk = Label("", 11, level=3, num=True)
        self.sp_up = Sparkline(color=QtGui.QColor("#ff9f0a"))
        self.sp_dn = Sparkline(color=QtGui.QColor("#64d2ff"))
        for s in (self.sp_up, self.sp_dn):
            s.setFixedHeight(28)
        self.net.setLayout(vbox(hbox(Label("网络", 12, W.DemiBold, level=2), None, self.disk),
                                hbox(self.net_up, (self.sp_up, 1), spacing=6),
                                hbox(self.net_dn, (self.sp_dn, 1), spacing=6), spacing=2, margins=(12, 8, 12, 8)))
        self.top = Label("", 11.5, level=2, wrap=True)
        self.top.setFixedHeight(84)
        topcard = Card(radius=18)
        topcard.setLayout(vbox(Label("占用最高", 12, W.DemiBold, level=2), self.top, spacing=2, margins=(12, 8, 12, 8)))
        self.setLayout(vbox(hbox(self.cpu, self.gpu, self.mem, spacing=8),
                            hbox((self.net, 3), (topcard, 2), spacing=8), spacing=8))
        self.ttimer = QtCore.QTimer(self, interval=3000, timeout=self._top)
        for l in (self.net_up, self.net_dn):
            l.setFixedWidth(84)

    def set_data(self, d: dict):
        if not self.active:
            return
        h = d.get("history") or {}
        self.cpu.v.setText(f"{d.get('cpu', 0):.0f}%")
        self.cpu.spark.set_values(h.get("cpu") or [])
        cores = d.get("cpu_per_core") or []
        self.cpu.sub.setText(f"{len(cores)} 线程" if cores else "")
        g = d.get("gpu")
        self.gpu.v.setText("--" if g is None else f"{g:.0f}%")
        self.gpu.spark.set_values([x for x in (h.get("gpu") or []) if x is not None])
        gm = d.get("gpu_mem")
        self.gpu.sub.setText(f"显存 {fmt_bytes(gm)}" if gm else "")
        self.mem.v.setText(f"{d.get('mem_pct', 0):.0f}%")
        self.mem.spark.set_values(h.get("mem") or [])
        self.mem.sub.setText(f"{fmt_bytes(d.get('mem_used', 0))} / {fmt_bytes(d.get('mem_total', 0))}")
        self.net_up.setText(f"↑ {fmt_bytes(d.get('net_up', 0), True)}")
        self.net_dn.setText(f"↓ {fmt_bytes(d.get('net_down', 0), True)}")
        self.sp_up.set_values(h.get("net_up") or [])
        self.sp_dn.set_values(h.get("net_down") or [])
        self.disk.setText(f"磁盘 读 {fmt_bytes(d.get('disk_r', 0), True)} · 写 {fmt_bytes(d.get('disk_w', 0), True)}")

    def _top(self):
        def done(rows):
            if rows:
                self.top.setText("\n".join(f"{r['name'].removesuffix('.exe')[:18]:<18}  {r['cpu']:.1f}%  {fmt_bytes(r['mem'])}"
                                           for r in rows[:4]))
        run_bg(self.ctx.perf.top_processes, 4, on_done=done)

    def on_show(self):
        super().on_show()
        st = getattr(self.ctx.perf, "state", None)
        if st:
            self.set_data(st)
        self._top()
        self.ttimer.start()

    def on_hide(self):
        super().on_hide()
        self.ttimer.stop()
