# -*- coding: utf-8 -*-
"""wisland 入口：创建服务、页面、灵动岛，把信号连成"活动"提示。"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import traceback
import winreg
from types import SimpleNamespace

from PySide6 import QtCore, QtGui, QtWidgets

from .core import bg
from .core.config import DATA_DIR, ROOT, cfg, expand

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Actions(QtCore.QObject):
    """跨页面的动作（热键 / 快捷按钮共用）。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._trans_req = -1
        self._trans_show_page = False

    def translate_clipboard(self, show_page: bool = False):
        text = QtGui.QGuiApplication.clipboard().text().strip()
        if not text:
            self.ctx.island.activity({"glyph": _G().TRANSLATE, "title": "剪贴板里没有文字"}, 2.0)
            return
        self.translate_text(text, show_page)

    def translate_text(self, text: str, show_page: bool = False):
        from .ui.theme import G
        text = text.strip()[:4000]
        if not text:
            return
        rid = self.ctx.translate.translate(text)
        self._trans_req = rid
        self._trans_show_page = show_page
        self.ctx.pages["trans"].start(text, rid)
        isl = self.ctx.island
        if show_page:
            isl.expand("trans")
        elif not isl.expanded:
            isl.activity({"glyph": G.TRANSLATE, "title": "翻译中…", "sub": text[:30]}, 20)

    def on_translated(self, rid: int, out: str):
        from .ui.theme import G
        isl = self.ctx.island
        if rid != self._trans_req or isl.expanded:
            return
        first = " ".join(out.split())
        isl.activity({"glyph": G.TRANSLATE, "title": first[:60], "sub": ""}, min(12.0, 3.5 + len(first) * 0.12))

    def on_trans_failed(self, rid: int, err: str):
        from .ui.theme import G
        if rid == self._trans_req and not self.ctx.island.expanded:
            self.ctx.island.activity({"glyph": G.TRANSLATE, "title": "翻译失败", "sub": err}, 4)


def _G():
    from .ui.theme import G
    return G


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "wisland")
            return True
    except OSError:
        return False


def _autostart_cmd() -> str:
    """开机自启命令：优先直接启动项目根目录的 Wisland.exe（无控制台窗口），缺省回退 wisland.vbs。"""
    exe = ROOT / "Wisland.exe"
    if exe.is_file():
        return f'"{exe}"'
    wscript = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")
    return f'"{wscript}" "{ROOT / "wisland.vbs"}"'


def _restart_cmd() -> list[str]:
    """重启时用的启动命令：沿用当前解释器（Wisland.exe / pythonw.exe / python.exe）跑 run.pyw。"""
    exe = sys.executable or ""
    script = str(ROOT / "run.pyw")
    if not exe:
        exe = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
    return [exe, script]


def fix_autostart():
    """旧版本直接用 .venv/Scripts/pythonw.exe 自启：在 uv 创建的环境里会弹出终端窗口，
    关掉窗口灵动岛也会退出。检测到旧的命令就改成通过 wisland.vbs 启动。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cur, _ = winreg.QueryValueEx(k, "wisland")
    except OSError:
        return
    # 便携版可与旧目录共存。只迁移当前安装目录的旧启动命令。
    root_prefix = os.path.normcase(str(ROOT)) + os.sep
    if root_prefix in os.path.normcase(str(cur)) and cur != _autostart_cmd():
        try:
            set_autostart(True)
        except OSError:
            pass


def set_autostart(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "wisland", 0, winreg.REG_SZ, _autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, "wisland")
            except OSError:
                pass


def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wisland.DynamicIsland")
    except Exception:  # noqa: BLE001
        pass
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Wisland")
    app.setApplicationDisplayName("Wisland")
    bg.init()

    lock = QtCore.QLockFile(str(DATA_DIR / "wisland.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        print("wisland 已在运行")
        return 0
    fix_autostart()

    from .services.audio import AudioService, BrightnessService
    from .services.clash import ClashService
    from .services.clipboard import ClipboardService
    from .services.hotspot import HotspotService
    from .services.mailcheck import MailCheckService
    from .services.media import MediaService
    from .services.notify import NotifyService
    from .services.stocks import StockService
    from .services.system import RadioService, WindowService
    from .services.lyrics import LyricsService
    from .services.translate import TranslateService
    from .services.weather import WeatherService, weather_glyph
    from .ui.island import Island
    from .ui.pages.home import HomePage, MessagesPage
    from .ui.pages.game_calendar import GameCalendarPage
    from .ui.pages.info import StocksPage, WeatherPage
    from .ui.pages.system import ControlsPage, styled_menu
    from .ui.pages.tools import ClipboardPage, TranslatePage
    from .ui.theme import KIND_COLORS, THEME_NAMES, G, theme
    from .ui.widgets import glyph_pixmap

    theme.set_mode(cfg.get("island.theme", "auto"))
    ctx = SimpleNamespace()
    ctx.media = MediaService()
    ctx.audio = AudioService()
    ctx.brightness = BrightnessService()
    ctx.radio = RadioService()
    ctx.hotspot = HotspotService()
    ctx.windows = WindowService()
    ctx.notify = NotifyService()
    ctx.stocks = StockService()
    ctx.weather = WeatherService()
    ctx.clash = ClashService()
    ctx.translate = TranslateService()
    ctx.lyrics = LyricsService()
    ctx.clipboard = ClipboardService()
    ctx.mailcheck = MailCheckService()
    from .live.service import LiveService
    ctx.live = LiveService()
    from .learn.service import LearnService
    ctx.learn = LearnService()
    ctx.actions = Actions(ctx)
    ctx.notify.opener = lambda path: ctx.windows.open_or_focus(path)
    ctx.clash.opener = lambda path: ctx.windows.open_or_focus(path)
    ctx.windows.notice.connect(lambda t: ctx.island and ctx.island.activity({"glyph": _G().MESSAGE, "title": t}, 5.0))
    ctx.island = None

    pages = [HomePage(ctx), MessagesPage(ctx), StocksPage(ctx), WeatherPage(ctx), ControlsPage(ctx),
             ClipboardPage(ctx), TranslatePage(ctx), GameCalendarPage(ctx)]
    ctx.pages = {p.key: p for p in pages}
    P = ctx.pages

    peak_cache = {"value": 0.0, "next": 0.0}

    def peak():
        """音频峰值最多每 150ms 查询一次；绘制帧复用缓存，避免每帧跨 COM 调用。"""
        now = time.monotonic()
        if now < peak_cache["next"]:
            return peak_cache["value"]
        peak_cache["next"] = now + 0.15
        try:
            peak_cache["value"] = ctx.audio.peak()
        except Exception:  # noqa: BLE001
            peak_cache["value"] = 0.0
        return peak_cache["value"]

    island = Island(pages, peak_fn=peak, foreground_fullscreen=ctx.windows.foreground_is_fullscreen)
    ctx.island = island
    compact = island.compact
    calendar = P["calendar"]
    calendar.deadlines_changed.connect(lambda n: island.nav.set_badge("calendar", n))

    # ---------------- 媒体 ----------------
    media_st = {"key": None, "lyr": None, "prev_view": None, "playing": False, "paused_pet": False}
    back_timer = QtCore.QTimer(app, singleShot=True, interval=5000)

    def update_lyrics(m):
        k = ctx.lyrics.key(m) if m.get("title") else None
        if k != media_st["lyr"]:
            media_st["lyr"] = k
            compact.set_lyrics(None)
        if k:
            lyr = ctx.lyrics.get(m)
            if lyr is not None and compact.lyrics is not lyr:
                compact.set_lyrics(lyr)

    def on_lyrics_ready(k):
        if k == media_st["lyr"]:
            update_lyrics(compact.media)
            island._kick()
    ctx.lyrics.ready.connect(on_lyrics_ready)

    def back_to_view():
        # 暂停超过 5 秒后统一显示贴纸；恢复播放时 on_media 会自动切回音乐。
        if not compact.playing() and compact.view == "music":
            compact.set_view("pet")
            media_st["paused_pet"] = True
            island._kick()
        media_st["prev_view"] = None
    back_timer.timeout.connect(back_to_view)

    def on_media(m):
        compact.set_media(m)
        P["home"].media.set_media(m)
        update_lyrics(m)
        playing = bool(m.get("playing") and m.get("title"))
        key = (m.get("app_id"), m.get("title"), m.get("artist"))
        if playing:
            back_timer.stop()
            if media_st["paused_pet"]:
                # 由暂停自动切到贴纸后，恢复播放必须切回歌曲界面。
                compact.set_view("music")
                media_st["paused_pet"] = False
            elif island.passthrough():
                compact.set_view("music")
            elif cfg.get("media.auto_show", True) and (not media_st["playing"] or key != media_st["key"]):
                if compact.view in ("clock", "pet"):
                    media_st["prev_view"] = compact.view
                    compact.set_view("music")
        elif m.get("title") and compact.view == "music" and not back_timer.isActive():
            back_timer.start()
        media_st["playing"], media_st["key"] = playing, key
        island._kick()
    ctx.media.changed.connect(on_media)

    def on_cover(img):
        compact.set_cover(img)
        P["home"].media.set_cover(img)
        island._kick()
    ctx.media.cover_changed.connect(on_cover)

    # ---------------- 音量（外部改动也弹出提示，像手机一样） ----------------
    vol_state = {"init": True, "last": None}

    def on_volume(v, muted):
        P["ctl"].set_volume(v, muted)
        key = (round(v, 3), muted)
        if vol_state["init"]:
            vol_state["init"] = False
        elif key != vol_state["last"] and not island.expanded:
            act = {"type": "volume", "glyph": G.MUTE if muted else G.VOLUME, "value": v, "muted": muted}
            if compact.activity and compact.activity.get("type") == "volume":
                compact.update_activity(**act, until=time.monotonic() + 1.8)
            else:
                island.activity(act, 1.8)
            island._kick()
        vol_state["last"] = key
    ctx.audio.volume_changed.connect(on_volume)
    compact.set_view(cfg.get("island.compact_view", "clock"))

    def on_wheel(d):
        v = compact.cycle_view(d)
        cfg.set("island.compact_view", v)
        island._kick()
    island.wheel_compact.connect(on_wheel)
    ctx.brightness.changed.connect(P["ctl"].set_brightness)
    ctx.radio.changed.connect(P["ctl"].set_radio)

    # ---------------- Clash ----------------
    clash_state = {"mode": None}

    def on_clash(d):
        P["ctl"].set_clash(d)
        m = d.get("mode")
        if d.get("ok") and clash_state["mode"] and m != clash_state["mode"] and not island.expanded:
            names = {"rule": "规则模式", "global": "全局模式", "direct": "直连模式"}
            island.activity({"glyph": G.GLOBE, "title": "Clash", "sub": names.get(m, m)}, 2.2)
        if d.get("ok"):
            clash_state["mode"] = m
    ctx.clash.updated.connect(on_clash)
    ctx.clash.notice.connect(lambda t: island.activity({"glyph": G.GLOBE, "title": "Clash", "sub": t}, 4))

    # ---------------- 移动热点 ----------------
    ctx.hotspot.changed.connect(P["ctl"].set_hotspot)
    ctx.hotspot.notice.connect(lambda t: island.activity({"glyph": G.HOTSPOT, "title": t}, 3.5))



    # ---------------- 消息提醒 ----------------
    def on_notified(n):
        kind = n.get("kind", "other")
        glyph = {"mail": G.MAIL, "qq": G.CHAT, "wechat": G.MESSAGE}.get(kind, G.BELL)
        sub = "新邮件" if kind == "mail" else (n.get("sender") or "新消息")
        compact.react_sticker()
        P["home"].pet.react("surprise")
        island.activity({"glyph": glyph, "color": KIND_COLORS.get(kind, KIND_COLORS["other"]),
                         "title": n.get("name", kind), "sub": sub}, 4.0)
        if P["msg"].active:
            P["msg"].refresh()

    def on_counts(c):
        compact.badges = dict(c)
        island.nav.set_badge("msg", sum(c.values()))
        if P["msg"].active:
            P["msg"].refresh()
        island._kick()
    ctx.notify.notified.connect(on_notified)
    ctx.notify.counts_changed.connect(on_counts)
    ctx.notify.notice.connect(lambda t: island.activity({"glyph": G.BELL, "title": "消息", "sub": t}, 4.5))

    # 用户手动把 QQ / 微信切到前台，视为已经查看该应用的新消息。
    def clear_foreground_messages():
        if not (ctx.notify.counts.get("qq") or ctx.notify.counts.get("wechat")):
            return
        exe = ctx.windows.foreground_exe()
        kind = "qq" if exe == "qq.exe" else ("wechat" if exe in ("weixin.exe", "wechat.exe") else "")
        if kind and ctx.notify.counts.get(kind, 0):
            ctx.notify.clear(kind)

    island.flash.connect(ctx.notify.on_flash)
    ctx.mailcheck.new_mail.connect(lambda user, n: ctx.notify._emit(
        {"kind": "mail", "name": "邮件", "source": "imap", "time": time.time()}))

    # ---------------- 股票 ----------------
    ctx.stocks.updated.connect(P["stock"].set_data)

    def on_stock_alert(a):
        if "stock" not in island.page_keys():
            return
        pct = a.get("pct") or 0
        col = theme.up() if pct > 0 else theme.down()
        island.activity({"source": "stock", "glyph": G.STOCK, "color": col, "title": a.get("name", a.get("code", "")),
                         "sub": a.get("text", ""), "sub_color": col}, 5.0)
    ctx.stocks.alert.connect(on_stock_alert)

    def sync_stock_page():
        if "stock" in island.page_keys():
            ctx.stocks.start()
        else:
            ctx.stocks.stop()
            if compact.activity and compact.activity.get("source") == "stock":
                compact.activity = None
                island._kick()

    # ---------------- 天气 ----------------
    def on_weather(d):
        P["weather"].set_data(d)
        if d.get("ok") or d.get("temp") is not None:
            g, fam = weather_glyph(d.get("icon"))
            compact.weather = (g, f"{round(d.get('temp', 0))}°", fam)
        island._kick()
    ctx.weather.updated.connect(on_weather)

    # ---------------- 翻译 ----------------
    ctx.translate.finished.connect(ctx.actions.on_translated)
    ctx.translate.failed.connect(ctx.actions.on_trans_failed)

    # ---------------- 实时字幕：收起态显示最新一句 ----------------
    # 收起态两行显示：上面日语、下面中文；有人说话时优先显示，安静几秒后回到原视图（不打断音乐）
    sub_st = {"sid": None}

    def on_partial(jp):
        if jp:
            compact.set_sub(jp=jp)
            island._kick()

    def on_segment(sid, jp):
        if sid != sub_st["sid"]:
            sub_st["sid"] = sid
        compact.set_sub(jp=jp)
        island._kick()

    def on_zh(sid, zh):
        if zh:
            compact.set_sub(zh=zh)
            island._kick()

    def on_running(on):
        compact.set_sub_running(on)
        island._kick()
    ctx.live.partial.connect(on_partial)
    ctx.live.segment.connect(on_segment)
    ctx.live.live_zh.connect(on_zh)
    ctx.live.final_zh.connect(on_zh)
    ctx.live.running_changed.connect(on_running)
    island.play_pause_requested.connect(lambda: ctx.media.play_pause())
    ctx.learn.notice.connect(lambda t: island.activity({"glyph": _G().CHECK, "title": t}, 2.6))
    ctx.live.error.connect(lambda m: island.activity({"glyph": G.LIVE, "title": "实时字幕", "sub": m}, 4))

    # ---------------- 热键 ----------------
    def on_hotkey(name):
        if name == "toggle":
            island.toggle()
        elif name == "translate":
            ctx.actions.translate_clipboard()
        elif name == "clipboard":
            island.toggle("clip")
    island.hotkey.connect(on_hotkey)

    # ---------------- 设置窗口 ----------------
    def apply_pages():
        """页面显示 / 顺序改动后：重建导航、按需启停股票行情、刷新消息。"""
        island.apply_page_layout()
        calendar.set_monitoring("calendar" in island.page_keys())
        sync_stock_page()
        if P["msg"].active:
            P["msg"].refresh()
        island._kick()

    def open_settings():
        from .ui.settings import SettingsWindow
        old = getattr(ctx, "settings", None)
        if old is not None:
            try:
                old.close()
                old.deleteLater()
            except RuntimeError:
                pass
        win = SettingsWindow(ctx, {"apply_pages": apply_pages, "quit": app.quit,
                                   "autostart_get": autostart_enabled, "autostart_set": set_autostart})
        ctx.settings = win
        win.present()
    ctx.open_settings = open_settings
    ctx.apply_pages = apply_pages

    def restart_app():
        """退出并重启：交给独立辅助进程，等本进程退出、锁文件清掉后再拉起新实例。"""
        island.activity({"glyph": G.REFRESH, "title": "正在重启…"}, 1.2)
        # 辅助进程沿用和 run.pyw 一样的启动器：.venv 里的 pythonw.exe 在 uv 环境下
        # 其实是控制台程序，优先用 Wisland.exe 免得闪一下黑框。
        scripts = os.path.join(ROOT, ".venv", "Scripts")
        helper = sys.executable
        for name in ("Wisland.exe", "pythonw.exe"):
            cand = os.path.join(scripts, name)
            if os.path.isfile(cand):
                helper = cand
                break
        args = [helper, "-m", "wisland.core.relaunch", str(os.getpid()),
                str(DATA_DIR / "wisland.lock"), str(ROOT)] + _restart_cmd()
        try:
            subprocess.Popen(args, cwd=str(ROOT), close_fds=True,
                             creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            island.activity({"glyph": G.REFRESH, "title": "重启失败", "sub": "请看 data/wisland.log"}, 3)
            return
        QtCore.QTimer.singleShot(120, app.quit)

    def build_menu(menu: QtWidgets.QMenu):
        menu.addAction("设置…").triggered.connect(open_settings)
        menu.addAction("展开 / 收起").triggered.connect(island.toggle)
        tm = menu.addMenu("主题")
        for mode, label in THEME_NAMES:
            a = tm.addAction(("✓  " if cfg.get("island.theme") == mode else "    ") + label)
            a.triggered.connect(lambda _=False, m=mode: (cfg.set("island.theme", m), theme.set_mode(m)))
        em = menu.addMenu("展开方式")
        for mode, label in (("hover", "悬停展开"), ("always", "常驻展开"), ("never", "长关")):
            a = em.addAction(("✓  " if island.expand_mode() == mode else "    ") + label)
            a.triggered.connect(lambda _=False, m=mode: island.set_expand_mode(m))
        a = menu.addAction(("✓  " if island.passthrough() else "    ") + "可穿透")
        a.triggered.connect(lambda: island.set_passthrough(not island.passthrough()))
        a = menu.addAction(("✓  " if island.capture_visible() else "    ") + "参与截图")
        a.triggered.connect(lambda: island.set_capture_visible(not island.capture_visible()))
        a = menu.addAction(("✓  " if autostart_enabled() else "    ") + "开机自启")
        a.triggered.connect(lambda: set_autostart(not autostart_enabled()))
        menu.addSeparator()
        menu.addAction("退出并重启").triggered.connect(restart_app)
        menu.addAction("退出 wisland").triggered.connect(app.quit)

    # 右键灵动岛 = 打开设置窗口（快捷项留在托盘菜单里）
    def show_menu(pos):
        open_settings()
    island.menu_requested.connect(show_menu)
    # 导航：「主页」标签放在播放器封面正上方
    def nav_anchor():
        m = P["home"].media
        if m.width() < 10:
            return None
        g = m.mapToGlobal(QtCore.QPoint(m.width() // 2, 0))
        return island.nav.mapFromGlobal(g).x()
    island.nav.anchor_fn = nav_anchor

    # 主页的「保持展开」「可穿透」按钮
    home = P["home"]
    MODE_UI = {"hover": (G.EYE, "悬停展开"), "always": (G.PIN, "常驻展开"), "never": (G.EYE_OFF, "长关")}
    NEXT = {"hover": "always", "always": "never", "never": "hover"}
    # 按钮只在 常驻展开 ↔ 悬停展开 之间切换；长关用双击灵动岛切换
    home.a_pin.clicked.connect(lambda: island.set_expand_mode("hover" if island.expand_mode() == "always" else "always"))
    home.a_pt.clicked.connect(lambda: island.set_passthrough(not island.passthrough()))
    home.a_mute.clicked.connect(lambda: island.set_capture_visible(not island.capture_visible()))
    home.a_live.clicked.connect(lambda: island.set_fullscreen_visible(not island.fullscreen_visible()))
    island.capture_visible_changed.connect(home.set_capture_visible)
    island.fullscreen_visible_changed.connect(home.set_fullscreen_visible)

    def on_mode(mode):
        # 按钮只表示 常驻展开 / 悬停展开；长关不在按钮上显示
        if mode == "never":
            mode = "hover"
        g, label = MODE_UI.get(mode, MODE_UI["hover"])
        home.a_pin.set_on(mode == "always", g, label)

    def on_pt(on):
        home.a_pt.set_on(on, None, "可穿透")
        if on:
            # 正在播放时保留音乐状态；没有歌曲时才显示用户贴纸。
            compact.set_view("music" if compact.playing() else "pet")
            island._kick()
    island.mode_changed.connect(on_mode)
    island.passthrough_changed.connect(on_pt)
    on_mode(island.expand_mode())
    home.a_pt.set_on(island.passthrough(), None, "可穿透")
    home.set_capture_visible(island.capture_visible())
    home.set_fullscreen_visible(island.fullscreen_visible())
    if island.passthrough():
        compact.set_view("music" if compact.playing() else "pet")
    island.nav.add_right_button(G.GEAR, "设置", lambda: open_settings())

    app_icon = QtGui.QIcon(glyph_pixmap(G.APPS, 32, QtGui.QColor("#4f8cff")))
    app.setWindowIcon(app_icon)
    tray = QtWidgets.QSystemTrayIcon(app_icon, app)
    tray.setToolTip("wisland 灵动岛")
    tmenu = QtWidgets.QMenu()
    tmenu.aboutToShow.connect(lambda: (tmenu.clear(), build_menu(tmenu)))
    tray.setContextMenu(tmenu)
    tray.activated.connect(lambda r: island.toggle() if r == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    # ---------------- 收起态：时间天气与小形象每隔几十秒自动轮换 ----------------
    def auto_cycle():
        if island.expanded or island.passthrough() or compact.view not in ("clock", "pet"):
            return
        compact.set_view("pet" if compact.view == "clock" else "clock")
        island._kick()
    cyc = int(cfg.get("island.auto_cycle_s", 30) or 0)
    if cyc > 0:
        QtCore.QTimer(app, interval=cyc * 1000, timeout=auto_cycle).start()

    # ---------------- 全屏隐藏、置顶恢复与前台消未读（共用 1s 定时器） ----------------
    def check_foreground_and_fullscreen():
        clear_foreground_messages()
        if island.fullscreen_visible():
            island.set_fullscreen_hidden(False)
        else:
            try:
                island.set_fullscreen_hidden(ctx.windows.foreground_is_fullscreen(int(island.winId())))
            except Exception:  # noqa: BLE001
                pass
        island.ensure_topmost()
    fs_timer = QtCore.QTimer(app, interval=1000, timeout=check_foreground_and_fullscreen)
    # ---------------- 启动 ----------------
    island.show()
    if os.environ.get("WISLAND_DEBUG"):
        def _dbg():
            print(f"[dbg] geo={island.geometry()} body={island.body} path_empty={island.path.isEmpty()} "
                  f"expanded={island.expanded} vis={island.isVisible()} sw={island.sw.x:.0f} sh={island.sh.x:.0f} "
                  f"compact_a={island.compact_a.x:.2f} page={island._page_key} mode={island.mode}", flush=True)
        QtCore.QTimer(app, interval=2000, timeout=_dbg).start()
        _dbg()
    for s in (ctx.media, ctx.audio, ctx.brightness, ctx.radio, ctx.hotspot, ctx.windows, ctx.notify,
              ctx.weather, ctx.clash, ctx.translate, ctx.clipboard, ctx.mailcheck, ctx.learn):
        try:
            if hasattr(s, "start"):
                s.start()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    sync_stock_page()
    calendar.set_monitoring("calendar" in island.page_keys())
    fs_timer.start()
    if os.environ.get("WISLAND_OPEN_SETTINGS"):     # 调试用：启动后直接弹出设置窗口
        QtCore.QTimer.singleShot(1200, open_settings)

    def shutdown():
        ctx.live.stop(wait=True)
        for s in (ctx.media, ctx.audio, ctx.brightness, ctx.radio, ctx.hotspot, ctx.notify, ctx.stocks,
                  ctx.weather, ctx.clash, ctx.translate, ctx.clipboard, ctx.mailcheck, ctx.learn):
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
        cfg.save()
        lock.unlock()
    app.aboutToQuit.connect(shutdown)
    return app.exec()
