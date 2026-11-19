# -*- coding: utf-8 -*-
"""媒体会话：Windows GlobalSystemMediaTransportControls（SMTC）。

所有 WinRT 调用都在一个专用 asyncio 线程中执行；信号从该线程发出（Qt 自动排队到主线程）。
"""
from __future__ import annotations

import asyncio
from collections import deque
import ctypes
import datetime as _dt
import json
import threading
import time
import traceback

from PySide6 import QtCore, QtGui

from wisland.core.config import DATA_DIR, cfg
from wisland.core.bg import run_bg
from wisland.services.netease import NeteaseLog

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _Manager,
    )
    from winrt.windows.storage.streams import Buffer as _Buffer, InputStreamOptions as _ISO
except Exception:  # noqa: BLE001
    traceback.print_exc()
    _Manager = None

POLL_S = 0.7
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3
VK_CONTROL, VK_MENU, VK_L = 0x11, 0x12, 0x4C
VK_LEFT, VK_RIGHT, VK_SPACE = 0x25, 0x27, 0x20
_user32 = ctypes.WinDLL("user32")
_netease_control_lock = threading.Lock()


def media_key(vk: int):
    """模拟键盘媒体键：播放器没有接入系统媒体控件（SMTC）时也能控制大多数播放器。"""
    try:
        _user32.keybd_event(vk, 0, 0x1, 0)          # KEYEVENTF_EXTENDEDKEY
        _user32.keybd_event(vk, 0, 0x1 | 0x2, 0)    # | KEYEVENTF_KEYUP
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def key_chord(*vks: int):
    """发送组合键；网易云默认用 Ctrl+Alt+L 喜欢 / 取消喜欢当前歌曲。"""
    try:
        for vk in vks:
            _user32.keybd_event(vk, 0, int(vk in (VK_LEFT, VK_RIGHT)), 0)
        for vk in reversed(vks):
            _user32.keybd_event(vk, 0, 0x2 | int(vk in (VK_LEFT, VK_RIGHT)), 0)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _find_netease_windows():
    host = _user32.FindWindowW("OrpheusBrowserHost", None)
    if not host:
        return 0, 0, 0, 0
    cef = _user32.FindWindowExW(host, None, "CefBrowserWindow", None)
    widget = _user32.FindWindowExW(cef, None, "Chrome_WidgetWin_0", None) if cef else 0
    rwhh = _user32.FindWindowExW(widget, None, "Chrome_RenderWidgetHostHWND", None) if widget else 0
    if not rwhh:
        from ctypes import wintypes as W
        pid_host = W.DWORD()
        _user32.GetWindowThreadProcessId(host, ctypes.byref(pid_host))
        res = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

        def cb(hw, _):
            pid = W.DWORD()
            _user32.GetWindowThreadProcessId(hw, ctypes.byref(pid))
            if pid.value == pid_host.value:
                ch = _user32.FindWindowExW(hw, None, "Chrome_RenderWidgetHostHWND", None)
                if ch:
                    res.append(ch)
            return True

        _user32.EnumWindows(WNDENUMPROC(cb), 0)
        rwhh = res[0] if res else 0
    return host, cef, widget, rwhh


_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000


def _get_exstyle(hwnd: int) -> int:
    fn = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
    fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
    fn.restype = ctypes.c_ssize_t
    return int(fn(hwnd, _GWL_EXSTYLE))


def _set_exstyle(hwnd: int, ex: int):
    fn = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    fn.restype = ctypes.c_ssize_t
    fn(hwnd, _GWL_EXSTYLE, int(ex))


def _prepare_netease_widget(host: int, cef: int, widget: int):
    """确保隐藏/最小化状态下 CEF 子窗口也有完整尺寸，用于后台投递点击消息。"""
    from ctypes import wintypes as W
    dpi = _user32.GetDpiForWindow(host) if hasattr(_user32, "GetDpiForWindow") else 96
    dpr = (dpi / 96.0) if dpi and dpi > 0 else 1.0
    was_hidden = not bool(_user32.IsWindowVisible(host))
    orig_ex = None
    if was_hidden:
        # 临时设为 TOOLWINDOW 再 SHOWMINNOACTIVE：防止任务栏闪出网易云图标又消失
        orig_ex = _get_exstyle(host)
        _set_exstyle(host, (orig_ex | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW)
        _user32.ShowWindow(host, 7)  # SW_SHOWMINNOACTIVE：保持在屏幕外最小化态，不弹窗不抢焦点
    rc = W.RECT()
    _user32.GetClientRect(widget, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 100 or h <= 100:
        d3d = _user32.FindWindowExW(widget, None, "Intermediate D3D Window", None)
        if d3d:
            _user32.GetWindowRect(d3d, ctypes.byref(rc))
            w, h = rc.right - rc.left, rc.bottom - rc.top
        if w <= 100 or h <= 100:
            w, h = round(1061 * dpr), round(752 * dpr)
        swp = 0x0002 | 0x0004 | 0x0010 | 0x0040  # SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
        _user32.SetWindowPos(cef, 0, 0, 0, w, h, swp)
        _user32.SetWindowPos(widget, 0, 0, 0, w, h, swp)
        time.sleep(0.02)
    return w, h, dpr, orig_ex


def _restore_netease_host(host: int, orig_ex: int | None, delay: float = 0.04):
    if orig_ex is None:
        return
    if delay > 0:
        time.sleep(delay)
    _user32.ShowWindow(host, 0)  # SW_HIDE：恢复托盘隐藏态
    _set_exstyle(host, orig_ex)


def _post_click(widget: int, x: int, y: int) -> bool:
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    _user32.PostMessageW(widget, 0x0200, 0, lp)  # WM_MOUSEMOVE
    down = _user32.PostMessageW(widget, 0x0201, 1, lp)  # WM_LBUTTONDOWN
    up = _user32.PostMessageW(widget, 0x0202, 0, lp)    # WM_LBUTTONUP
    return bool(down and up)


def seek_netease(seconds: float, duration: float) -> bool:
    """向网易云 PC 端 CEF 窗口的底部进度条发送后台点击消息，实现无焦点、最小化/托盘态下的进度跳转。"""
    if duration <= 0:
        return False
    try:
        ratio = min(1.0, max(0.0, float(seconds) / float(duration)))
        host, cef, widget, _ = _find_netease_windows()
        if not widget:
            return False
        w, h, dpr, orig_ex = _prepare_netease_widget(host, cef, widget)
        try:
            # 网易云 3.x 底部播放栏高度 80px (逻辑)，进度条横跨整个窗口宽度、位于底栏顶边 (H - 82*dpr)
            x = max(2, min(w - 3, int(round(ratio * w))))
            y = int(round(h - 82.0 * dpr))
            _post_click(widget, x, y)
            return True
        finally:
            _restore_netease_host(host, orig_ex, delay=0.03)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


_ACC_CACHE_PATH = DATA_DIR / "netease_acc_cache.json"
_acc_cache_lock = threading.Lock()
_acc_pos_cache: dict[str, dict[str, tuple[int, int]]] | None = None


def _acc_cache_key(w: int, h: int, dpr: float) -> str:
    return f"{w}x{h}@{dpr:.2f}"


def _load_acc_cache() -> dict[str, dict[str, tuple[int, int]]]:
    global _acc_pos_cache
    if _acc_pos_cache is not None:
        return _acc_pos_cache
    data: dict[str, dict[str, tuple[int, int]]] = {}
    try:
        if _ACC_CACHE_PATH.exists():
            raw = json.loads(_ACC_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, dict):
                        data[k] = {
                            str(n): (int(pt[0]), int(pt[1]))
                            for n, pt in v.items()
                            if isinstance(pt, (list, tuple)) and len(pt) == 2
                        }
    except Exception:  # noqa: BLE001
        pass
    _acc_pos_cache = data
    return data


def _record_acc_coords(w: int, h: int, dpr: float, root_loc, found: dict[str, tuple[int, int, int, int]]):
    if not root_loc or not found:
        return
    rx, ry, _, _ = root_loc
    key = _acc_cache_key(w, h, dpr)
    with _acc_cache_lock:
        cache = _load_acc_cache()
        slot = dict(cache.get(key) or {})
        changed = False
        for name, (tx, ty, tw, th) in found.items():
            pt = ((tx - rx) + tw // 2, (ty - ry) + th // 2)
            if slot.get(name) != pt:
                slot[name] = pt
                changed = True
        if changed:
            cache[key] = slot
            try:
                _ACC_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass


def _get_cached_acc_coords(w: int, h: int, dpr: float) -> dict[str, tuple[int, int]]:
    with _acc_cache_lock:
        cache = _load_acc_cache()
        exact = cache.get(_acc_cache_key(w, h, dpr))
        if exact:
            return dict(exact)
        suffix = f"@{dpr:.2f}"
        for k, v in cache.items():
            if k.endswith(suffix) and v:
                return dict(v)
    return {}


def _find_acc_targets(rwhh: int, targets: set[str], dpr: float = 1.0, *, footer=False):
    """从 CEF 的 IAccessible 树定位侧栏、顶栏或底部播放控件。"""
    from ctypes import wintypes as W
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
    oleacc = ctypes.WinDLL("oleacc", use_last_error=True)
    initialized = ole32.CoInitialize(None) in (0, 1)

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", W.BYTE * 8)]

    class VARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", W.WORD), ("wReserved1", W.WORD), ("wReserved2", W.WORD), ("wReserved3", W.WORD),
            ("val", ctypes.c_uint64), ("pad", ctypes.c_uint64),
        ]

    IID_IAccessible = GUID(0x618736E0, 0x3C3D, 0x11CF, (W.BYTE * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))
    self_v = VARIANT()
    self_v.vt = 3
    self_v.val = 0

    def vtbl_of(ptr):
        return ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))

    def get_name(pacc) -> str:
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, VARIANT, ctypes.POINTER(ctypes.c_void_p))(vtbl_of(pacc)[10])
        bstr = ctypes.c_void_p()
        if fn(pacc, self_v, ctypes.byref(bstr)) == 0 and bstr.value:
            s = ctypes.wstring_at(bstr.value)
            oleaut32.SysFreeString(bstr)
            return s
        return ""

    def get_loc(pacc):
        fn = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(W.LONG), ctypes.POINTER(W.LONG),
            ctypes.POINTER(W.LONG), ctypes.POINTER(W.LONG), VARIANT,
        )(vtbl_of(pacc)[22])
        x, y, w, h = W.LONG(), W.LONG(), W.LONG(), W.LONG()
        if fn(pacc, ctypes.byref(x), ctypes.byref(y), ctypes.byref(w), ctypes.byref(h), self_v) == 0:
            return (x.value, y.value, w.value, h.value)
        return None

    def child_count(pacc) -> int:
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(W.LONG))(vtbl_of(pacc)[8])
        cnt = W.LONG()
        return cnt.value if fn(pacc, ctypes.byref(cnt)) == 0 else 0

    def release(ptr):
        if ptr:
            fn = ctypes.WINFUNCTYPE(W.ULONG, ctypes.c_void_p)(vtbl_of(ptr)[2])
            fn(ptr)

    pacc = ctypes.c_void_p()
    if oleacc.AccessibleObjectFromWindow(rwhh, 0xFFFFFFFC, ctypes.byref(IID_IAccessible), ctypes.byref(pacc)) != 0 or not pacc.value:
        if initialized:
            ole32.CoUninitialize()
        return None, {}

    found: dict[str, tuple[int, int, int, int]] = {}
    q: deque[tuple[int, int, bool]] = deque([(pacc.value, 0, False)])
    try:
        root_loc = get_loc(pacc.value)
        rx, ry, rw, rh = root_loc if root_loc else (0, 0, 0, 0)
        max_x = max(360.0 * dpr, rw * 0.40) if rw > 0 else 0.0
        max_y = (rh - 82.0 * dpr) if rh > 160 else 0.0

        while q and len(found) < len(targets):
            node, depth, owned = q.popleft()
            try:
                loc = get_loc(node) if depth > 0 else root_loc
                if depth > 0 and root_loc and loc and loc[2] > 0 and loc[3] > 0:
                    x_rel = loc[0] - rx
                    y_rel = loc[1] - ry
                    if x_rel + loc[2] <= 0 or y_rel + loc[3] <= 0:
                        continue
                    if footer:
                        if max_y > 0 and y_rel + loc[3] < max_y:
                            continue
                    elif x_rel > max_x or (max_y > 0 and y_rel > max_y):
                        continue

                name = get_name(node)
                in_region = not footer or (root_loc and loc and max_y <= loc[1] - ry + loc[3] / 2 < rh)
                if in_region and name in targets and name not in found and loc and loc[2] > 0 and loc[3] > 0:
                    found[name] = loc
                    if len(found) == len(targets):
                        break

                if depth >= 14:
                    continue
                cnt = child_count(node)
                if 0 < cnt < 100:
                    arr = (VARIANT * cnt)()
                    got = W.LONG()
                    if oleacc.AccessibleChildren(ctypes.c_void_p(node), 0, cnt, arr, ctypes.byref(got)) == 0:
                        for i in range(got.value):
                            if arr[i].vt == 9 and arr[i].val:
                                child = ctypes.c_void_p()
                                q_fn = ctypes.WINFUNCTYPE(
                                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
                                )(vtbl_of(arr[i].val)[0])
                                if q_fn(arr[i].val, ctypes.byref(IID_IAccessible), ctypes.byref(child)) == 0 and child.value:
                                    q.append((child.value, depth + 1, True))
                                release(arr[i].val)
            finally:
                if owned:
                    release(node)
        return root_loc, found
    finally:
        while q:
            node, _depth, owned = q.popleft()
            if owned:
                release(node)
        release(pacc.value)
        if initialized:
            ole32.CoUninitialize()


def control_netease(targets: tuple[str, ...]) -> bool:
    """直接点击网易云底栏里已定位的真实按钮，无需向前台游戏发送按键。"""
    try:
        with _netease_control_lock:
            host, cef, widget, rwhh = _find_netease_windows()
            if not widget or not rwhh:
                return False
            w, h, dpr, orig_ex = _prepare_netease_widget(host, cef, widget)
            try:
                root_loc, found = _find_acc_targets(rwhh, set(targets), dpr, footer=True)
                if root_loc is None:
                    return False
                for name in targets:
                    if name not in found:
                        continue
                    x, y, width, height = found[name]
                    x += width // 2 - root_loc[0]
                    y += height // 2 - root_loc[1]
                    if 0 <= x < w and 0 <= y < h:
                        return _post_click(widget, x, y)
                return False
            finally:
                _restore_netease_host(host, orig_ex)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


def switch_netease_mode(target_mode: str, cur_mode: str = "") -> bool:
    """在后台切换网易云播放模式：'fm' = 漫游模式，'ai' = 心动模式。"""
    target_name = "sidebar_fm" if target_mode == "fm" else "sidebar_heartbeat"
    try:
        host, cef, widget, rwhh = _find_netease_windows()
        if not widget or not rwhh:
            return False
        w, h, dpr, orig_ex = _prepare_netease_widget(host, cef, widget)
        try:
            root_loc, found = _find_acc_targets(rwhh, {target_name, "dropdown"}, dpr)
            if root_loc and found:
                _record_acc_coords(w, h, dpr, root_loc, found)
                if target_name in found:
                    rx, ry, _, _ = root_loc
                    tx, ty, tw, th = found[target_name]
                    _post_click(widget, (tx - rx) + tw // 2, (ty - ry) + th // 2)
                    return True
                if "dropdown" in found:
                    # 当前正在播放详情/黑胶页（漫游默认展开此页），先收起再点侧边栏
                    rx, ry, _, _ = root_loc
                    tx, ty, tw, th = found["dropdown"]
                    _post_click(widget, (tx - rx) + tw // 2, (ty - ry) + th // 2)
                    for wait_s in (0.12, 0.12):
                        time.sleep(wait_s)
                        root_loc2, found2 = _find_acc_targets(rwhh, {target_name}, dpr)
                        if root_loc2 and target_name in found2:
                            _record_acc_coords(w, h, dpr, root_loc2, found2)
                            rx, ry, _, _ = root_loc2
                            tx, ty, tw, th = found2[target_name]
                            _post_click(widget, (tx - rx) + tw // 2, (ty - ry) + th // 2)
                            return True
                    cached = _get_cached_acc_coords(w, h, dpr)
                    if target_name in cached:
                        _post_click(widget, *cached[target_name])
                        return True
                    return False

            # 窗口处于最小化/托盘隐藏时 Chromium 会暂停 Accessibility 树；回退到同尺寸/同 DPI 的缓存坐标
            cached = _get_cached_acc_coords(w, h, dpr)
            if cur_mode == "fm" and target_mode != "fm" and "dropdown" in cached and target_name in cached:
                _post_click(widget, *cached["dropdown"])
                time.sleep(0.14)
                _post_click(widget, *cached[target_name])
                return True
            if target_name in cached:
                _post_click(widget, *cached[target_name])
                return True
            return False
        finally:
            _restore_netease_host(host, orig_ex, delay=0.05)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

_FRIENDLY = [
    ("cloudmusic", "网易云音乐"),
    ("bilibili", "哔哩哔哩"),
    ("chrome", "Chrome"),
    ("zen", "Zen"),
    ("msedge", "Edge"),
    ("firefox", "Firefox"),
    ("spotify", "Spotify"),
    ("qqmusic", "QQ音乐"),
]


def friendly_name(app_id: str) -> str:
    low = (app_id or "").lower()
    for key, name in _FRIENDLY:
        if key in low:
            return name
    s = app_id or ""
    for sep in ("!", "\\", "/"):
        s = s.rsplit(sep, 1)[-1]
    if s.lower().endswith(".exe"):
        s = s[:-4]
    return s or "媒体"


def _secs(v) -> float:
    """TimeSpan -> 秒（pywinrt 映射为 datetime.timedelta；兼容 int ticks）。"""
    if v is None:
        return 0.0
    if isinstance(v, _dt.timedelta):
        return v.total_seconds()
    try:
        return float(v) / 1e7
    except Exception:  # noqa: BLE001
        return 0.0


_cover_lock = threading.Lock()
_cover_client = None
_cover_cache: dict[str, QtGui.QImage] = {}


def _get_cover_cached(url: str) -> QtGui.QImage | None:
    if not url:
        return None
    u = url.replace("http://", "https://", 1)
    full_url = u + ("&" if "?" in u else "?") + "param=240y240"
    with _cover_lock:
        return _cover_cache.get(full_url)


def _download_cover(url: str):
    """下载网易云专辑封面（小图）-> QImage | None。复用直连连接池与内存缓存，避免切歌时每次走代理握手。"""
    from wisland.core.bg import http_client
    try:
        u = url.replace("http://", "https://", 1)
        full_url = u + ("&" if "?" in u else "?") + "param=240y240"
        with _cover_lock:
            if full_url in _cover_cache:
                return _cover_cache[full_url]
        r = http_client().get(full_url, follow_redirects=True)
        r.raise_for_status()
        img = QtGui.QImage.fromData(r.content)
        if img.isNull():
            return None
        with _cover_lock:
            _cover_cache[full_url] = img
            while len(_cover_cache) > 16:
                _cover_cache.pop(next(iter(_cover_cache)))
        return img
    except Exception:  # noqa: BLE001
        return None


def _load_local_cover(path: str) -> QtGui.QImage | None:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        img = QtGui.QImage.fromData(data)
        return None if img.isNull() else img
    except Exception:  # noqa: BLE001
        return None


def _empty_state() -> dict:
    return {
        "has_session": False, "app_id": "", "app_name": "", "title": "", "artist": "",
        "album": "", "playing": False, "liked": None, "play_mode": "", "position": 0.0, "duration": 0.0,
        "stamp": time.monotonic(), "can_prev": False, "can_next": False, "song_id": "", "source": "",
    }


class MediaService(QtCore.QObject):
    changed = QtCore.Signal(dict)
    cover_changed = QtCore.Signal(object)   # QtGui.QImage | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: dict = _empty_state()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mgr = None
        self._session = None
        self._track_key = None
        self._cover_song_id = ""
        self._cover_tries = 0
        self._last_emit = None
        self._netease = NeteaseLog()

    # ---------------- 生命周期 ----------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if _Manager is None:
            self.changed.emit(dict(self.state))
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wisland-media", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(lambda: None)
            except RuntimeError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            self._loop = None
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _main(self):
        while not self._stop.is_set():
            try:
                if self._mgr is None:
                    self._mgr = await _Manager.request_async()
                await self._poll()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                self._mgr = None
                self._session = None
            # 分段睡眠以便快速退出；每 0.1 秒重新读一次间隔，设置里改了不用重启
            last = time.monotonic()
            while not self._stop.is_set():
                left = last + self.poll_interval() - time.monotonic()
                if left <= 0:
                    break
                await asyncio.sleep(min(0.1, left))

    # ---------------- 轮询 ----------------
    def poll_interval(self) -> float:
        """本次轮询的间隔（秒）：读设置里的 media.poll_ms，钳在 100 ms ~ 3 s。"""
        try:
            ms = int(cfg.get("media.poll_ms", POLL_S * 1000) or 0)
        except Exception:  # noqa: BLE001
            ms = int(POLL_S * 1000)
        return min(3.0, max(0.1, ms / 1000.0))

    def _choose(self, sessions):
        prio = [str(p).lower() for p in (cfg.get("media.priority") or [])]

        def rank(s):
            aid = (s.source_app_user_model_id or "").lower()
            for i, p in enumerate(prio):
                if p in aid:
                    return i
            return len(prio)

        cands = []
        for s in sessions:
            try:
                info = s.get_playback_info()
                playing = info is not None and int(info.playback_status) == _PLAYING
            except Exception:  # noqa: BLE001
                playing = False
            cands.append((0 if playing else 1, rank(s), s))
        if not cands:
            return None
        cands.sort(key=lambda t: (t[0], t[1]))
        return cands[0][2]

    async def _poll(self):
        sessions = list(self._mgr.get_sessions() or [])
        s = self._choose(sessions)
        # 网易云默认不接入系统媒体控件（即使接入也没有进度），优先用它的本地日志
        ne = None
        if cfg.get("media.netease_log", True):
            try:
                self._netease.poll()
                ne = self._netease.snapshot()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        if ne is not None:
            aid = (s.source_app_user_model_id or "").lower() if s is not None else ""
            smtc_playing = False
            if s is not None:
                try:
                    info = s.get_playback_info()
                    smtc_playing = info is not None and int(info.playback_status) == _PLAYING
                except Exception:  # noqa: BLE001
                    pass
            if s is None or "cloudmusic" in aid or (ne["playing"] and not smtc_playing):
                self._session = s if s is not None and "cloudmusic" in aid else None
                await self._publish_netease(ne)
                return
        self._session = s
        if s is None:
            st = _empty_state()
            if self.state.get("has_session") or self._last_emit is None:
                self._track_key = None
                self._cover_song_id = ""
                self.cover_changed.emit(None)
                self._publish(st, force=True)
            return

        app_id = s.source_app_user_model_id or ""
        try:
            props = await s.try_get_media_properties_async()
        except Exception:  # noqa: BLE001
            props = None
        title = (props.title if props else "") or ""
        artist = (props.artist if props else "") or ""
        album = (props.album_title if props else "") or ""

        info = s.get_playback_info()
        playing = bool(info and int(info.playback_status) == _PLAYING)
        can_prev = can_next = False
        if info and info.controls:
            can_prev = bool(info.controls.is_previous_enabled)
            can_next = bool(info.controls.is_next_enabled)

        pos = dur = 0.0
        try:
            tl = s.get_timeline_properties()
            if tl:
                start = _secs(tl.start_time)
                dur = max(0.0, _secs(tl.end_time) - start)
                pos = max(0.0, _secs(tl.position) - start)
                # 按 last_updated_time 外推到“现在”
                if playing:
                    lut = tl.last_updated_time
                    if isinstance(lut, _dt.datetime) and lut.year > 1601:
                        now = _dt.datetime.now(_dt.timezone.utc)
                        if lut.tzinfo is None:
                            lut = lut.replace(tzinfo=_dt.timezone.utc)
                        age = (now - lut).total_seconds()
                        if 0 < age < 6 * 3600:
                            pos += age
                if dur > 0:
                    pos = min(pos, dur)
        except Exception:  # noqa: BLE001
            pass

        st = {
            "has_session": True, "app_id": app_id, "app_name": friendly_name(app_id),
            "title": title, "artist": artist, "album": album, "playing": playing, "liked": None, "play_mode": "",
            "position": pos, "duration": dur, "stamp": time.monotonic(),
            "can_prev": can_prev, "can_next": can_next, "song_id": "", "source": "smtc",
        }

        # 先立即发布歌名/歌手/进度，避免被封面读取阻塞
        self._publish(st)

        key = (app_id, title, artist, album)
        if key != self._track_key:
            self._track_key = key
            self._cover_tries = 0
            img = await self._read_cover(props)
            if self._track_key == key:
                self.cover_changed.emit(img)
                if img is None:
                    self._cover_tries = 1
        elif 0 < self._cover_tries < 6:
            # 浏览器等常常在标题之后才给出缩略图，重试几次
            self._cover_tries += 1
            img = await self._read_cover(props)
            if img is not None and self._track_key == key:
                self._cover_tries = 0
                self.cover_changed.emit(img)

    async def _publish_netease(self, ne: dict):
        sid = str(ne.get("song_id") or "")
        st = {
            "has_session": True, "app_id": "cloudmusic.exe", "app_name": "网易云音乐",
            "title": ne["title"], "artist": ne["artist"], "album": ne["album"], "playing": ne["playing"],
            "liked": ne.get("liked"), "play_mode": ne.get("play_mode") or "",
            "position": ne["position"], "duration": ne["duration"], "stamp": ne["stamp"],
            "can_prev": True, "can_next": True, "song_id": sid, "source": "netease",
        }
        # 先立即发布歌名/歌手/进度，不等待网络下载封面（否则每次切歌会被封面下载卡住约 1 秒）
        self._publish(st)
        # 封面地址与本地缩略图都算进 key；切歌时若封面尚未就绪先保留旧封面，避免闪成空图。
        cover_url = ne.get("cover") or ""
        cover_file = ne.get("cover_file") or ""
        key = ("netease", sid, cover_url, cover_file)
        if key != self._track_key:
            self._track_key = key
            if self._cover_song_id != sid:
                img = _load_local_cover(cover_file) if cover_file else None
                if img is not None:
                    self._cover_song_id = sid
                    self.cover_changed.emit(img)
                elif cover_url:
                    cached = _get_cover_cached(cover_url)
                    if cached is not None:
                        self._cover_song_id = sid
                        self.cover_changed.emit(cached)
                    else:
                        asyncio.create_task(self._load_netease_cover(key, sid, cover_url))
                elif ne.get("meta_ready"):
                    self._cover_song_id = sid
                    self.cover_changed.emit(None)

    async def _load_netease_cover(self, key: tuple, sid: str, cover_url: str):
        img = await asyncio.get_running_loop().run_in_executor(None, _download_cover, cover_url)
        if self._track_key == key and self._cover_song_id != sid:
            self._cover_song_id = sid
            self.cover_changed.emit(img)

    def _publish(self, st: dict, force: bool = False):
        cmp = {k: v for k, v in st.items() if k not in ("stamp", "position")}
        prev = self.state
        drift = False
        if prev.get("has_session") and st.get("has_session"):
            # 位置与外推值差太多（拖动进度、暂停时）才视为变化
            expect = prev.get("position", 0.0)
            if prev.get("playing"):
                expect += st["stamp"] - prev.get("stamp", st["stamp"])
            drift = abs(expect - st["position"]) > 1.5
        self.state = st
        if force or drift or cmp != self._last_emit:
            self._last_emit = cmp
            self.changed.emit(dict(st))

    async def _read_cover(self, props):
        try:
            thumb = props.thumbnail if props else None
            if thumb is None:
                return None
            stream = await thumb.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > 20 * 1024 * 1024:
                return None
            buf = _Buffer(size)
            out = await stream.read_async(buf, size, _ISO.READ_AHEAD)
            data = bytes(memoryview(out))[: int(out.length)]
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            img = QtGui.QImage.fromData(data)
            return None if img.isNull() else img
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None

    # ---------------- 控制 ----------------
    def _submit(self, make_coro, fallback=None, *, direct=None):
        """依次尝试播放器窗口、系统媒体会话和按键。"""
        def without_loop():
            if (direct is None or not direct()) and fallback is not None:
                fallback()

        loop = self._loop
        if loop is None:
            if direct is not None or fallback is not None:
                run_bg(without_loop)
            return

        async def wrapper():
            ok = False
            try:
                if direct is not None:
                    ok = await asyncio.get_running_loop().run_in_executor(None, direct)
                s = self._session
                if not ok and s is not None:
                    ok = bool(await make_coro(s))
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            if not ok and fallback is not None:
                fallback()
            if self._mgr is not None:
                for delay in ((0.08,) if ok and direct is None else (0.04, 0.08, 0.15)):
                    try:
                        await asyncio.sleep(delay)
                        await self._poll()
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()

        coro = wrapper()
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            if direct is not None or fallback is not None:
                run_bg(without_loop)

    def _transport(self, make_coro, media_vk: int, netease_vk: int, buttons: tuple[str, ...]):
        source = str(self.state.get("source") or "").lower()
        app_id = str(self.state.get("app_id") or "").lower()
        if source == "netease" or "cloudmusic" in app_id:
            async def cloudmusic_session(session):
                if "cloudmusic" in (session.source_app_user_model_id or "").lower():
                    return await make_coro(session)
                return False

            self._submit(cloudmusic_session, lambda: key_chord(VK_CONTROL, VK_MENU, netease_vk),
                         direct=lambda: control_netease(buttons))
        else:
            self._submit(make_coro, lambda: media_key(media_vk))

    def play_pause(self):
        buttons = ("pause", "play") if self.state.get("playing") else ("play", "pause")
        self._transport(lambda s: s.try_toggle_play_pause_async(), VK_MEDIA_PLAY_PAUSE, VK_SPACE, buttons)

    def next(self):
        self._transport(lambda s: s.try_skip_next_async(), VK_MEDIA_NEXT, VK_RIGHT, ("next",))

    def prev(self):
        self._transport(lambda s: s.try_skip_previous_async(), VK_MEDIA_PREV, VK_LEFT, ("pre",))

    def like(self):
        """喜欢 / 取消喜欢网易云当前歌曲（网易云默认全局快捷键 Ctrl+Alt+L）。"""
        source = str(self.state.get("source") or "").lower()
        app_id = str(self.state.get("app_id") or "").lower()
        if source == "netease" or "cloudmusic" in app_id:
            liked = self.state.get("liked")
            if isinstance(liked, bool):
                st = dict(self.state)
                st["liked"] = not liked          # 先即时反馈；后续带歌曲 id 的日志事件会校正结果
                self._netease.set_liked(str(st.get("song_id") or ""), st["liked"])
                self._publish(st, force=True)
            key_chord(VK_CONTROL, VK_MENU, VK_L)

    def seek(self, seconds: float):
        dur = float(self.state.get("duration") or 0.0)
        pos = max(0.0, min(float(seconds or 0.0), dur) if dur > 0 else float(seconds or 0.0))
        source = str(self.state.get("source") or "").lower()
        app_id = str(self.state.get("app_id") or "").lower()
        is_netease = source == "netease" or "cloudmusic" in app_id

        # 立即乐观更新进度与歌词锚点
        if self.state.get("has_session"):
            st = dict(self.state)
            st["position"] = pos
            st["stamp"] = time.monotonic()
            if is_netease:
                self._netease.set_position(pos)
            self._publish(st, force=True)

        if is_netease and dur > 0:
            loop = self._loop
            if loop is None:
                seek_netease(pos, dur)
                return

            async def ne_go():
                await asyncio.get_running_loop().run_in_executor(None, seek_netease, pos, dur)
                for delay in (0.05, 0.12):
                    await asyncio.sleep(delay)
                    await self._poll()

            try:
                asyncio.run_coroutine_threadsafe(ne_go(), loop)
            except RuntimeError:
                seek_netease(pos, dur)
            return

        def go(s):
            start = 0.0
            try:
                start = _secs(s.get_timeline_properties().start_time)
            except Exception:  # noqa: BLE001
                pass
            return s.try_change_playback_position_async(int((pos + start) * 1e7))
        self._submit(go)

    def toggle_netease_mode(self):
        """在漫游模式（fm）与心动模式（ai）之间互相切换；非这两种模式时默认进入漫游模式。"""
        cur = str(self.state.get("play_mode") or "").lower()
        target = "ai" if cur == "fm" else "fm"
        if self.state.get("has_session"):
            st = dict(self.state)
            st["play_mode"] = target
            self._netease.set_play_mode(target)
            self._publish(st, force=True)
        loop = self._loop
        if loop is None:
            switch_netease_mode(target, cur)
            return

        async def go():
            ok = await asyncio.get_running_loop().run_in_executor(None, switch_netease_mode, target, cur)
            if ok:
                for delay in (0.05, 0.12, 0.25, 0.48):
                    await asyncio.sleep(delay)
                    await self._poll()
            else:
                await self._poll()

        try:
            asyncio.run_coroutine_threadsafe(go(), loop)
        except RuntimeError:
            switch_netease_mode(target, cur)
