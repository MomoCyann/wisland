# -*- coding: utf-8 -*-
"""音量（pycaw，主线程 COM）与亮度（Twinkle Tray CLI / DDC-CI / WMI，后台单线程）。"""
from __future__ import annotations

import ctypes
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes as W

from PySide6 import QtCore, QtGui

from wisland.core.bg import run_bg, run_hidden, ui
from wisland.core.config import cfg, expand


# ======================================================================
# 音量
# ======================================================================
class AudioService(QtCore.QObject):
    """默认播放设备的主音量。所有 COM 调用只在主线程。"""

    volume_changed = QtCore.Signal(float, bool)   # (0..1, muted)
    sessions_changed = QtCore.Signal(list)        # 每应用音量会话（普通字典，不暴露 COM 对象）

    POLL_MS = 250
    SESSION_POLL_S = 0.9
    DEVICE_CHECK_S = 3.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enum = None
        self._dev_id = None
        self._vol = None      # IAudioEndpointVolume
        self._meter = None    # IAudioMeterInformation
        self._last = None     # (volume, muted)
        self._last_dev_check = 0.0
        self._out_cache: list[dict] = []   # 播放设备列表（后台刷新，读缓存不阻塞界面）
        self._out_at = 0.0
        self._out_busy = False
        self._sessions_on = False
        self._sessions_next = 0.0
        self._sess_mgr = None   # IAudioSessionManager2，随设备一起缓存
        self._session_data: list[dict] = []
        self._session_controls: dict[str, list] = {}
        self._session_digest = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)

    # ---------------- 设备 ----------------
    def _acquire(self) -> bool:
        try:
            import comtypes
            from pycaw.pycaw import (IAudioEndpointVolume, IAudioMeterInformation,
                                     IMMDeviceEnumerator)
            try:
                from pycaw.constants import CLSID_MMDeviceEnumerator
            except Exception:  # noqa: BLE001
                from pycaw.pycaw import CLSID_MMDeviceEnumerator  # type: ignore
            if self._enum is None:
                self._enum = comtypes.CoCreateInstance(
                    CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
            dev = self._enum.GetDefaultAudioEndpoint(0, 1)   # eRender, eMultimedia
            self._dev_id = dev.GetId()
            try:
                from pycaw.utils import AudioUtilities
                self._sess_mgr = AudioUtilities.CreateDevice(dev).AudioSessionManager
            except Exception:  # noqa: BLE001
                self._sess_mgr = None
            self._vol = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None) \
                .QueryInterface(IAudioEndpointVolume)
            try:
                self._meter = dev.Activate(IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None) \
                    .QueryInterface(IAudioMeterInformation)
            except Exception:  # noqa: BLE001
                self._meter = None
            self._last_dev_check = time.monotonic()
            return True
        except Exception:  # noqa: BLE001
            # 没有播放设备时会走到这里
            self._vol = self._meter = None
            self._sess_mgr = None
            self._dev_id = None
            self._last_dev_check = time.monotonic()
            return False

    def _check_device(self):
        """便宜地检查默认设备是否变了（只取 ID 字符串）。"""
        now = time.monotonic()
        if now - self._last_dev_check < self.DEVICE_CHECK_S and self._vol is not None:
            return
        self._last_dev_check = now
        try:
            if self._enum is None:
                self._acquire()
                return
            dev_id = self._enum.GetDefaultAudioEndpoint(0, 1).GetId()
            if dev_id != self._dev_id or self._vol is None:
                self._acquire()
        except Exception:  # noqa: BLE001
            self._vol = self._meter = None
            self._sess_mgr = None
            self._dev_id = None

    def _ev(self):
        if self._vol is None:
            self._acquire()
        return self._vol

    def _call(self, fn, default=None):
        """调用 COM，出错则重新获取设备再试一次。"""
        for attempt in range(2):
            ev = self._ev()
            if ev is None:
                return default
            try:
                return fn(ev)
            except Exception:  # noqa: BLE001
                self._vol = self._meter = None
                if attempt == 1:
                    return default
        return default

    # ---------------- 生命周期 ----------------
    def start(self):
        self._acquire()
        self._poll()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        try:
            self._check_device()
            cur = (round(self.volume(), 4), self.muted())
            if cur != self._last:
                self._last = cur
                self.volume_changed.emit(cur[0], cur[1])
            now = time.monotonic()
            if self._sessions_on and now >= self._sessions_next:
                self._sessions_next = now + self.SESSION_POLL_S
                self._poll_sessions()
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def _notify_soon(self):
        QtCore.QTimer.singleShot(0, self._poll)

    # ---------------- API ----------------
    def available(self) -> bool:
        return self._ev() is not None

    def volume(self) -> float:
        return float(self._call(lambda ev: ev.GetMasterVolumeLevelScalar(), 0.0) or 0.0)

    def set_volume(self, v: float):
        v = max(0.0, min(1.0, float(v)))
        self._call(lambda ev: ev.SetMasterVolumeLevelScalar(v, None))
        self._notify_soon()

    def muted(self) -> bool:
        return bool(self._call(lambda ev: ev.GetMute(), False))

    def set_muted(self, b: bool):
        self._call(lambda ev: ev.SetMute(1 if b else 0, None))
        self._notify_soon()

    def toggle_mute(self):
        self.set_muted(not self.muted())

    def step(self, delta: float):
        """delta 为 0..1 刻度，例如 +0.02。调大音量时自动取消静音。"""
        self.set_volume(self.volume() + delta)
        if delta > 0 and self.muted():
            self.set_muted(False)

    def peak(self) -> float:
        m = self._meter
        if m is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(m.GetPeakValue())))
        except Exception:  # noqa: BLE001
            self._meter = None
            self._vol = None
            return 0.0

    # ---------------- 应用音量合成器 ----------------
    def set_session_polling(self, on: bool):
        self._sessions_on = bool(on)
        if on:
            # 页面展开动画期间不立刻做 COM 会话枚举，避免打开控制页时主线程顿一下。
            self._sessions_next = time.monotonic() + 0.35

    def audio_sessions(self) -> list[dict]:
        return [dict(x) for x in self._session_data]

    @staticmethod
    def _session_name(exe: str, display: str, system: bool) -> str:
        if system:
            return "系统声音"
        if display and not display.startswith("@"):
            return display
        base = os.path.basename(exe).lower()
        known = {"cloudmusic.exe": "网易云音乐", "msedge.exe": "Microsoft Edge",
                 "chrome.exe": "Google Chrome", "firefox.exe": "Firefox",
                 "qqmusic.exe": "QQ音乐", "spotify.exe": "Spotify"}
        return known.get(base, os.path.splitext(os.path.basename(exe))[0] or "未知应用")

    def _iter_sessions(self):
        """枚举音频会话。

        不走 AudioUtilities.GetAllSessions()：它每次都重新 CoCreateInstance +
        GetDefaultAudioEndpoint，单次约 90ms，在主线程上足以卡住音量条的过渡动画。
        这里复用 _acquire() 缓存下来的 AudioSessionManager2，单次约 0.1ms。
        """
        from pycaw.api.audiopolicy import IAudioSessionControl2
        from pycaw.utils import AudioSession

        if self._sess_mgr is None:
            if not self._acquire():
                return []
        if self._vol is None:
            self._acquire()
        try:
            enum = self._sess_mgr.GetSessionEnumerator()
            out = []
            for i in range(enum.GetCount()):
                ctl = enum.GetSession(i)
                if ctl is None:
                    continue
                ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                if ctl2 is not None:
                    out.append(AudioSession(ctl2))
            return out
        except Exception:  # noqa: BLE001
            # 设备被拔掉等：丢掉缓存，下次重新获取
            self._sess_mgr = None
            self._vol = self._meter = None
            return []

    def _poll_sessions(self):
        try:
            grouped: dict[str, dict] = {}
            controls: dict[str, list] = {}
            for session in self._iter_sessions():
                try:
                    state = getattr(session.State, "value", session.State)
                    if int(state) == 2:           # Expired
                        continue
                    pid = int(session.ProcessId or 0)
                    process = session.Process
                    exe = ""
                    if process is not None:
                        try:
                            exe = process.exe()
                        except Exception:  # noqa: BLE001
                            exe = ""
                    system = pid == 0
                    ident = str(getattr(session, "Identifier", "") or "")
                    key = "system" if system else ("exe:" + os.path.normcase(exe) if exe else f"session:{ident or pid}")
                    vol = session.SimpleAudioVolume
                    value = max(0.0, min(1.0, float(vol.GetMasterVolume())))
                    muted = bool(vol.GetMute())
                    display = str(getattr(session, "DisplayName", "") or "").strip()
                    item = grouped.get(key)
                    if item is None:
                        item = {"key": key, "pid": pid, "name": self._session_name(exe, display, system),
                                "exe": exe, "volume": value, "muted": muted,
                                "active": int(state) == 1, "system": system, "_values": [value], "_mutes": [muted]}
                        grouped[key] = item
                    else:
                        item["active"] = bool(item["active"] or int(state) == 1)
                        item["_values"].append(value)
                        item["_mutes"].append(muted)
                    controls.setdefault(key, []).append(vol)
                except Exception:  # noqa: BLE001
                    continue
            data = []
            old_order = {x.get("key"): i for i, x in enumerate(self._session_data)}
            for item in grouped.values():
                vals = item.pop("_values")
                muts = item.pop("_mutes")
                item["volume"] = sum(vals) / max(1, len(vals))
                item["muted"] = all(muts)
                data.append(item)
            data.sort(key=lambda x: (not x["active"], old_order.get(x["key"], 10_000), x["name"].lower()))
            digest = tuple((x["key"], round(x["volume"], 3), x["muted"], x["active"], x["name"])
                           for x in data)
            self._session_controls = controls
            self._session_data = data
            if digest != self._session_digest:
                self._session_digest = digest
                self.sessions_changed.emit(self.audio_sessions())
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def set_session_volume(self, key: str, value: float):
        value = max(0.0, min(1.0, float(value)))
        for ctl in self._session_controls.get(key, []):
            try:
                ctl.SetMasterVolume(value, None)
            except Exception:  # noqa: BLE001
                pass
        self._sessions_next = 0.0

    def set_session_muted(self, key: str, muted: bool):
        for ctl in self._session_controls.get(key, []):
            try:
                ctl.SetMute(1 if muted else 0, None)
            except Exception:  # noqa: BLE001
                pass
        self._sessions_next = 0.0

    def toggle_session_mute(self, key: str):
        item = next((x for x in self._session_data if x.get("key") == key), None)
        if item is not None:
            self.set_session_muted(key, not bool(item.get("muted")))

    # ---------------- 输出设备（切换默认播放设备） ----------------
    def _enum_output(self) -> list[dict]:
        """枚举活动的播放设备：[{id, name, default}]。

        会自己初始化 COM（仅限非主线程），所以既能在主线程调用，也能丢到线程池里跑。
        GetDeviceEnumerator + GetAllDevices + 逐个读 FriendlyName 是十几次 COM 往返，
        在主线程做会明显卡一下——打开控制页时改走后台线程。
        """
        co = None
        if threading.current_thread() is not threading.main_thread():
            try:
                import comtypes
                comtypes.CoInitialize()
                co = comtypes
            except Exception:  # noqa: BLE001
                co = None
        out: list[dict] = []
        try:
            from pycaw.constants import DEVICE_STATE, EDataFlow
            from pycaw.utils import AudioUtilities
            enum = AudioUtilities.GetDeviceEnumerator()
            cur = enum.GetDefaultAudioEndpoint(0, 1).GetId()
            for d in AudioUtilities.GetAllDevices(data_flow=EDataFlow.eRender.value,
                                                  device_state=DEVICE_STATE.ACTIVE.value):
                props = d.properties or {}
                full_name = (d.FriendlyName or "").strip() or "未命名设备"
                name = str(props.get("{A45C254E-DF1C-4EFD-8020-67D146A850E0} 2") or "").strip()
                adapter = str(props.get("{B3F8FA53-0004-438E-9003-51A46E139BFC} 6") or "").strip()
                if not name:
                    cut = max(full_name.rfind(" ("), full_name.rfind(" （"))
                    name = full_name[:cut].strip() if cut > 0 and full_name.endswith((")", "）")) else full_name
                out.append({"id": d.id, "name": name or full_name, "adapter": adapter,
                            "full_name": full_name, "default": d.id == cur})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            if co is not None:
                try:
                    co.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass
        return out

    def _put_output(self, devs: list[dict]):
        if devs:
            self._out_cache = list(devs)
            self._out_at = time.monotonic()

    def output_devices(self, cached: bool = False) -> list[dict]:
        """cached=True 时只返回上次枚举的结果（绝不阻塞，可能为空）。"""
        if cached:
            return list(self._out_cache)
        devs = self._enum_output()
        self._put_output(devs)
        return devs

    def default_output(self, cached: bool = False) -> dict | None:
        devs = self.output_devices(cached=cached)
        return next((d for d in devs if d["default"]), devs[0] if devs else None)

    def warm_output(self, on_done=None):
        """后台枚举设备并更新缓存；完成后在主线程回调 on_done(devs)。"""
        if self._out_busy:
            return
        self._out_busy = True

        def done(devs):
            self._out_busy = False
            self._put_output(devs)
            if on_done:
                on_done(list(self._out_cache))

        def err(_e):
            self._out_busy = False

        run_bg(self._enum_output, on_done=done, on_error=err)

    def set_default_output(self, dev_id: str) -> bool:
        """切换默认播放设备（控制台 + 多媒体两个角色一起切，和系统设置的行为一致）。"""
        try:
            from pycaw.constants import ERole
            from pycaw.utils import AudioUtilities
            AudioUtilities.SetDefaultDevice(dev_id, roles=[ERole.eConsole, ERole.eMultimedia])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return False
        self._vol = self._meter = None        # 重新绑定到新设备
        self._last_dev_check = 0.0
        self._session_controls.clear()
        self._session_digest = None
        self._sessions_next = 0.0
        QtCore.QTimer.singleShot(150, self._poll)
        return True



# ======================================================================
# 亮度
# ======================================================================
_user32 = ctypes.WinDLL("user32")
_dxva2 = ctypes.windll.dxva2


class _PHYS(ctypes.Structure):
    _fields_ = [("h", W.HANDLE), ("desc", W.WCHAR * 128)]


class _MI(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


_MONENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)
_dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [W.HMONITOR, ctypes.POINTER(W.DWORD)]
_dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [W.HMONITOR, W.DWORD, ctypes.POINTER(_PHYS)]
_dxva2.DestroyPhysicalMonitors.argtypes = [W.DWORD, ctypes.POINTER(_PHYS)]
_dxva2.GetMonitorBrightness.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD),
                                        ctypes.POINTER(W.DWORD)]
_dxva2.SetMonitorBrightness.argtypes = [W.HANDLE, W.DWORD]
_dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [W.HANDLE, W.BYTE, ctypes.POINTER(W.DWORD),
                                                   ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD)]
_dxva2.SetVCPFeature.argtypes = [W.HANDLE, W.BYTE, W.DWORD]
_user32.GetMonitorInfoW.argtypes = [W.HMONITOR, ctypes.POINTER(_MI)]


def _enum_physical():
    """[(device_name, index_on_device, handle, description)]；调用方负责 _destroy。"""
    hmons = []

    def cb(h, dc, r, lp):
        hmons.append(h)
        return True

    _user32.EnumDisplayMonitors(None, None, _MONENUMPROC(cb), 0)
    out, arrays = [], []
    for hm in hmons:
        mi = _MI()
        mi.cbSize = ctypes.sizeof(_MI)
        _user32.GetMonitorInfoW(hm, ctypes.byref(mi))
        n = W.DWORD()
        if not _dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hm, ctypes.byref(n)) or n.value == 0:
            out.append((mi.szDevice, 0, None, ""))
            continue
        arr = (_PHYS * n.value)()
        if not _dxva2.GetPhysicalMonitorsFromHMONITOR(hm, n.value, arr):
            out.append((mi.szDevice, 0, None, ""))
            continue
        arrays.append((n.value, arr))
        for i, p in enumerate(arr):
            out.append((mi.szDevice, i, p.h, p.desc))
    return out, arrays


def _destroy(arrays):
    for n, arr in arrays:
        try:
            _dxva2.DestroyPhysicalMonitors(n, arr)
        except Exception:  # noqa: BLE001
            pass


def _ddc_get(h) -> int | None:
    if not h:
        return None
    mn, cur, mx = W.DWORD(), W.DWORD(), W.DWORD()
    if _dxva2.GetMonitorBrightness(h, ctypes.byref(mn), ctypes.byref(cur), ctypes.byref(mx)) and mx.value > mn.value:
        return round((cur.value - mn.value) * 100 / (mx.value - mn.value))
    ct = W.DWORD()
    if _dxva2.GetVCPFeatureAndVCPFeatureReply(h, 0x10, ctypes.byref(ct), ctypes.byref(cur), ctypes.byref(mx)) \
            and mx.value > 0:
        return round(cur.value * 100 / mx.value)
    return None


def _ddc_set(h, value: int) -> bool:
    if not h:
        return False
    mn, cur, mx = W.DWORD(), W.DWORD(), W.DWORD()
    if _dxva2.GetMonitorBrightness(h, ctypes.byref(mn), ctypes.byref(cur), ctypes.byref(mx)) and mx.value > mn.value:
        raw = mn.value + round(value * (mx.value - mn.value) / 100)
        if _dxva2.SetMonitorBrightness(h, raw):
            return True
    return bool(_dxva2.SetVCPFeature(h, 0x10, int(value)))


class _Wmi:
    """root\\wmi 亮度（笔记本内屏）。只在亮度工作线程里使用（MTA）。"""

    def __init__(self):
        self.svc = None
        self.failed = False

    def _conn(self):
        if self.svc is None and not self.failed:
            try:
                import comtypes.client
                self.svc = comtypes.client.CoGetObject(
                    "winmgmts:{impersonationLevel=impersonate}!\\\\.\\root\\wmi")
            except Exception:  # noqa: BLE001
                self.failed = True
        return self.svc

    @staticmethod
    def _p(o, name):
        return o.Properties_.Item(name).Value

    def read(self) -> list[tuple[str, int]]:
        svc = self._conn()
        if svc is None:
            return self._read_ps()
        try:
            return [(str(self._p(o, "InstanceName")), int(self._p(o, "CurrentBrightness")))
                    for o in svc.ExecQuery("SELECT * FROM WmiMonitorBrightness")
                    if self._p(o, "Active")]
        except Exception:  # noqa: BLE001
            # 没有内屏时 WMI 会抛“不支持”，属正常
            self.svc = None
            return []

    def set(self, value: int, instance: str | None = None) -> bool:
        svc = self._conn()
        if svc is None:
            return self._set_ps(value)
        try:
            ok = False
            for m in svc.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods"):
                if instance and str(self._p(m, "InstanceName")) != instance:
                    continue
                ip = m.Methods_.Item("WmiSetBrightness").InParameters.SpawnInstance_()
                ip.Properties_.Item("Timeout").Value = 0
                ip.Properties_.Item("Brightness").Value = int(value)
                m.ExecMethod_("WmiSetBrightness", ip)
                ok = True
            return ok
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.svc = None
            return False

    # 最后手段：PowerShell（慢，约 1 秒）
    @staticmethod
    def _read_ps():
        try:
            r = run_hidden(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance -Namespace root/wmi WmiMonitorBrightness | "
                            "ForEach-Object { \"$($_.InstanceName)|$($_.CurrentBrightness)\" }"], timeout=8)
            out = []
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                if "|" in line:
                    a, b = line.rsplit("|", 1)
                    out.append((a.strip(), int(b)))
            return out
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _set_ps(value):
        try:
            r = run_hidden(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance -Namespace root/wmi WmiMonitorBrightnessMethods | "
                            f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=0;Brightness={int(value)}}}"],
                           timeout=8)
            return r.returncode == 0
        except Exception:  # noqa: BLE001
            return False


def _init_worker():
    try:
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception:  # noqa: BLE001
        pass


class BrightnessService(QtCore.QObject):
    """显示器亮度。

    monitors: [{id, name, brightness(int 0..100 或 None), method("ddc"/"wmi"/None), device}]
    """

    changed = QtCore.Signal(list)

    DEBOUNCE_MS = 150
    TWINKLE_CHECK_S = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)
        ui(lambda: None)   # 确保 bg 的 _Invoker 在主线程创建（它是惰性创建的）
        self.monitors: list[dict] = []
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wisland-bright",
                                        initializer=_init_worker)
        self._wmi = _Wmi()
        self._pending: dict = {}      # id 或 None(全部) -> value
        self._busy = False
        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)
        self._debounce.timeout.connect(self._flush)
        self._twinkle_state = (0.0, False)
        self._twinkle_launched = False
        self._lock = threading.Lock()

    def start(self):
        self.refresh()

    def stop(self):
        self._debounce.stop()
        self._exec.shutdown(wait=False, cancel_futures=True)

    def _submit(self, fn, on_done=None):
        def task():
            try:
                res = fn()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return
            if on_done:
                ui(lambda: on_done(res))
        try:
            self._exec.submit(task)
        except RuntimeError:
            pass   # 已 stop

    # ---------------- 读取 ----------------
    def refresh(self):
        self._submit(self._read_all, self._on_read)

    def _read_all(self) -> list[dict]:
        phys, arrays = _enum_physical()
        try:
            mons = []
            for dev, idx, h, desc in phys:
                b = _ddc_get(h)
                mons.append({"id": f"{dev}#{idx}", "device": dev, "desc": desc,
                             "brightness": b, "method": "ddc" if b is not None else None,
                             "wmi": None})
        finally:
            _destroy(arrays)
        wmi = self._wmi.read()
        if wmi:
            # 内屏 DDC 不可用：把 WMI 实例依次分给 DDC 失败的显示器
            free = [m for m in mons if m["method"] is None]
            for (inst, val), m in zip(wmi, free):
                m.update(brightness=val, method="wmi", wmi=inst)
            if not free and not mons:
                mons.append({"id": "wmi#0", "device": "", "desc": "内置显示器",
                             "brightness": wmi[0][1], "method": "wmi", "wmi": wmi[0][0]})
        return mons

    def _on_read(self, mons: list[dict]):
        names = {}
        try:
            for s in QtGui.QGuiApplication.screens():
                names[s.name()] = (s.model() or s.manufacturer() or "").strip()
        except Exception:  # noqa: BLE001
            pass
        generic = ("generic pnp monitor", "通用即插即用监视器", "generic monitor", "")
        for i, m in enumerate(mons):
            desc = (m.get("desc") or "").strip()
            nm = desc if desc.lower() not in generic else (names.get(m["device"]) or f"显示器 {i + 1}")
            m["name"] = nm
            m["num"] = i + 1
        self.monitors = mons
        self._emit()
        if not any(m["method"] for m in mons):
            self._maybe_launch_twinkle()

    def _emit(self):
        self.changed.emit([{"id": m["id"], "name": m["name"], "brightness": m["brightness"]}
                           for m in self.monitors])

    # ---------------- 设置（防抖） ----------------
    def set(self, monitor_id, value):
        value = int(max(0, min(100, round(value))))
        dirty = False
        if monitor_id is None:
            self._pending = {None: value}
        else:
            self._pending[monitor_id] = value
        for m in self.monitors:
            if (monitor_id is None or m["id"] == monitor_id) and m["brightness"] != value:
                m["brightness"] = value
                dirty = True
        if dirty:
            self._emit()
        if not self._debounce.isActive() and not self._busy:
            self._debounce.start()

    def _flush(self):
        if self._busy:
            self._debounce.start()
            return
        if not self._pending:
            return
        jobs, self._pending = self._pending, {}
        mons = [dict(m) for m in self.monitors]
        self._busy = True
        self._submit(lambda: self._apply(jobs, mons), self._on_applied)

    def _on_applied(self, _res):
        self._busy = False
        if self._pending:
            self._debounce.start()

    def _twinkle_running(self) -> bool:
        t, val = self._twinkle_state
        if time.monotonic() - t < self.TWINKLE_CHECK_S:
            return val
        val = False
        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                n = (p.info.get("name") or "").lower()
                if "twinkle" in n:
                    val = True
                    break
        except Exception:  # noqa: BLE001
            pass
        self._twinkle_state = (time.monotonic(), val)
        return val

    def _twinkle_exe(self) -> str:
        p = expand(cfg.get("brightness.twinkle") or "")
        return p if p and os.path.isfile(p) else ""

    def _twinkle(self, args: list[str]) -> bool:
        exe = self._twinkle_exe()
        if not exe:
            return False
        try:
            run_hidden([exe, *args], timeout=5, cwd=os.path.dirname(exe))
            return True
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return False

    def _maybe_launch_twinkle(self):
        """直连方式全都不可用时，尝试把 Twinkle Tray 启动到托盘（只尝试一次）。"""
        if self._twinkle_launched or not self._twinkle_exe():
            return
        self._twinkle_launched = True

        def go():
            if not self._twinkle_running():
                from wisland.core.bg import launch
                launch(self._twinkle_exe())
                self._twinkle_state = (0.0, False)
        self._submit(go)

    def _apply(self, jobs: dict, mons: list[dict]):
        use_twinkle = self._twinkle_running() and bool(self._twinkle_exe())
        if None in jobs:
            v = jobs.pop(None)
            if not (use_twinkle and self._twinkle(["--All", f"--Set={v}"])):
                self._apply_direct([(m, v) for m in mons])
        todo = []
        for mid, v in jobs.items():
            m = next((x for x in mons if x["id"] == mid), None)
            if m is None:
                continue
            if use_twinkle and self._twinkle([f"--MonitorNum={m.get('num', 1)}", f"--Set={v}"]):
                continue
            todo.append((m, v))
        if todo:
            self._apply_direct(todo)
        return True

    def _apply_direct(self, items: list[tuple[dict, int]]):
        need_ddc = [(m, v) for m, v in items if m.get("method") == "ddc"]
        for m, v in items:
            if m.get("method") == "wmi":
                self._wmi.set(v, m.get("wmi"))
        if need_ddc:
            phys, arrays = _enum_physical()
            try:
                by_id = {f"{dev}#{idx}": h for dev, idx, h, _ in phys}
                for m, v in need_ddc:
                    h = by_id.get(m["id"])
                    if h:
                        _ddc_set(h, v)
            finally:
                _destroy(arrays)
