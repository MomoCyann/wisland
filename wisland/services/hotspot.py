# -*- coding: utf-8 -*-
"""移动热点（Windows 自带的「移动热点」/ Internet Connection Sharing）。

用的是 WinRT 的 NetworkOperatorTetheringManager（Windows.Networking.NetworkOperators），
和系统设置里那个开关是同一个东西：共享当前上网连接，默认 SSID / 密码沿用系统里已配置的。

调用注意：
- 只有存在"可共享的 Internet 连接"时才能拿到 manager（没有网时开关应该置灰）
- 所有 WinRT 调用在后台线程自己的 asyncio 循环里跑（和 RadioService 同款），UI 只收信号

信号
  changed(dict)  {available, on, ssid, clients, reason}
  notice(str)    操作失败时给用户看的一句话
"""
from __future__ import annotations

import asyncio
import threading
import traceback

from PySide6 import QtCore

from wisland.core.bg import ui
from wisland.core.config import cfg


class HotspotService(QtCore.QObject):
    changed = QtCore.Signal(dict)
    notice = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        ui(lambda: None)                     # 确保 bg 回调 invoker 在主线程创建
        self.state: dict = {"available": False, "on": False, "ssid": "", "clients": 0, "reason": ""}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last = None
        self._busy = False

    # ---------- lifecycle ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="wisland-hotspot", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.refresh()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def refresh(self):
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass

    def toggle(self, on: bool | None = None):
        """不传参数 = 切换；否则指定开 / 关。"""
        target = (not self.state.get("on")) if on is None else bool(on)
        loop = self._loop
        if loop is None or self._busy:
            return
        self._busy = True
        try:
            asyncio.run_coroutine_threadsafe(self._switch(target), loop)
        except RuntimeError:
            self._busy = False

    # ---------- worker ----------
    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            self._loop = None
            loop.close()

    async def _main(self):
        self._wake = asyncio.Event()
        try:
            interval = max(2.0, float(cfg.get("hotspot.interval_s") or 5))
        except (TypeError, ValueError):
            interval = 5.0
        while not self._stop.is_set():
            try:
                await self._poll()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            try:
                await asyncio.wait_for(self._wake.wait(), interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _manager(self):
        """当前联网连接对应的 tethering manager；没有网络时返回 None。"""
        from winrt.windows.networking.connectivity import NetworkInformation
        from winrt.windows.networking.networkoperators import NetworkOperatorTetheringManager
        try:
            prof = NetworkInformation.get_internet_connection_profile()
        except OSError:
            return None
        if prof is None:
            return None
        try:
            return NetworkOperatorTetheringManager.create_from_connection_profile(prof)
        except OSError:
            return None

    async def _poll(self):
        from winrt.windows.networking.networkoperators import TetheringOperationalState
        st = {"available": False, "on": False, "ssid": "", "clients": 0, "reason": ""}
        try:
            mgr = await self._manager()
            if mgr is None:
                st["reason"] = "当前没有可共享的网络连接"
            else:
                st["available"] = True
                st["on"] = int(mgr.tethering_operational_state) == int(TetheringOperationalState.ON)
                try:
                    st["clients"] = int(mgr.client_count or 0)
                except OSError:
                    pass
                try:
                    st["ssid"] = str(mgr.get_current_access_point_configuration().ssid or "")
                except OSError:
                    pass
        except Exception as e:  # noqa: BLE001
            st["reason"] = str(e)[:60]
        self.state = st
        if st != self._last:
            self._last = dict(st)
            self.changed.emit(dict(st))

    async def _switch(self, on: bool):
        from winrt.windows.networking.networkoperators import TetheringOperationStatus
        try:
            mgr = await self._manager()
            if mgr is None:
                self.notice.emit("移动热点：当前没有可共享的网络连接")
                return
            res = await (mgr.start_tethering_async() if on else mgr.stop_tethering_async())
            status = int(res.status) if res is not None else -1
            if status not in (int(TetheringOperationStatus.SUCCESS), int(TetheringOperationStatus.ALREADY_ON)):
                self.notice.emit(f"移动热点：{_status_text(status)}")
            await asyncio.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.notice.emit(f"移动热点：{str(e)[:60]}")
        finally:
            self._busy = False
            if self._wake:
                self._wake.set()


def _status_text(status: int) -> str:
    return {
        1: "未知错误",
        2: "移动宽带设备已关闭",
        3: "Wi-Fi 已关闭（热点需要 WLAN 打开）",
        4: "权限校验超时",
        5: "权限校验失败",
        6: "上一次操作还没结束",
        7: "蓝牙设备已关闭",
        8: "网络连接受限，无法共享",
        10: "无线功能被限制（可能是策略或飞行模式）",
        11: "频段冲突，换个频段试试",
    }.get(status, f"操作失败（{status}）")
