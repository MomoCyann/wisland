# -*- coding: utf-8 -*-
"""后台执行小工具：线程池跑阻塞任务，结果通过 Qt 信号回到主线程。"""
from __future__ import annotations

import asyncio
import subprocess
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6 import QtCore

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wisland")
_winrt_lock = threading.Lock()
_winrt_loop: asyncio.AbstractEventLoop | None = None
_http_lock = threading.Lock()
_http_direct = None


def winrt_loop() -> asyncio.AbstractEventLoop:
    """共享的后台 asyncio 事件循环线程（供 RadioService、HotspotService 等低频 WinRT 服务共用）。"""
    global _winrt_loop
    with _winrt_lock:
        if _winrt_loop is not None and _winrt_loop.is_running():
            return _winrt_loop
        ready = threading.Event()
        loop_holder: list[asyncio.AbstractEventLoop] = []

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop_holder.append(loop)
            ready.set()
            loop.run_forever()

        t = threading.Thread(target=_runner, name="wisland-winrt", daemon=True)
        t.start()
        ready.wait(timeout=2.0)
        _winrt_loop = loop_holder[0]
        return _winrt_loop


def http_client():
    """共享的直连 httpx.Client（连接池复用，trust_env=False）。"""
    global _http_direct
    if _http_direct is not None:
        return _http_direct
    with _http_lock:
        if _http_direct is None:
            import httpx
            _http_direct = httpx.Client(
                timeout=httpx.Timeout(8.0, connect=4.0),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                trust_env=False,
            )
        return _http_direct

CREATE_NO_WINDOW = 0x08000000


class _Invoker(QtCore.QObject):
    call = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn(), QtCore.Qt.ConnectionType.QueuedConnection)


_invoker: _Invoker | None = None


def init() -> None:
    """必须在主线程、QApplication 创建之后调用一次（让调度对象归属主线程）。"""
    global _invoker
    if _invoker is None:
        _invoker = _Invoker()
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            _invoker.moveToThread(app.thread())


def ui(fn: Callable[[], None]) -> None:
    """在主线程执行 fn（可在任意线程调用）。"""
    if _invoker is None:
        init()
    _invoker.call.emit(fn)


def run_bg(fn: Callable, *args, on_done: Callable | None = None, on_error: Callable | None = None):
    """后台执行 fn(*args)；完成后在主线程调用 on_done(result) / on_error(exc)。"""
    def task():
        try:
            res = fn(*args)
        except Exception as e:  # noqa: BLE001
            if on_error:
                # 调用方自己处理错误（例如后端没启动、网络超时）：不再打印整段堆栈
                ui(lambda e=e: on_error(e))
            else:
                traceback.print_exc()
            return
        if on_done:
            ui(lambda: on_done(res))
    return _pool.submit(task)


def run_hidden(args, timeout: float = 10.0, **kw) -> subprocess.CompletedProcess:
    """无窗口执行命令行（netsh 等），输出按系统编码解码。"""
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, **kw)


def launch(path: str, args: list[str] | None = None) -> bool:
    """启动外部程序（不等待）。"""
    import os
    try:
        if path.lower().endswith((".exe", ".bat", ".cmd")):
            subprocess.Popen([path, *(args or [])], cwd=os.path.dirname(path) or None,
                             creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP
        else:
            os.startfile(path)  # noqa: S606
        return True
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False
