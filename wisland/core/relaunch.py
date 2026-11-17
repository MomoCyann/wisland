# -*- coding: utf-8 -*-
"""「退出并重启」的辅助进程：等旧实例真正退出、清掉单实例锁，再按原来的方式把 wisland 拉起来。

单独做成模块（而不是在 app.py 里原地重启）是因为旧实例退出前一直占着
data/wisland.lock，新实例抢不到锁只会打印「wisland 已在运行」然后退出。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

FLAGS = 0x00000008 | 0x00000200        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _wait_exit(pid: int, timeout: float = 30.0) -> None:
    """等 pid 退出；进程已不存在或等超时都直接返回。"""
    if not pid:
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, int(pid))     # SYNCHRONIZE
        if h:
            try:
                k32.WaitForSingleObject(h, int(timeout * 1000))
            finally:
                k32.CloseHandle(h)
            return
    except Exception:  # noqa: BLE001
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)


def main(argv=None) -> int:
    """参数：<旧进程 pid> <锁文件> <工作目录> <启动命令...>。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 4:
        return 2
    pid, lock, cwd = int(argv[0]), argv[1], argv[2]
    cmd = argv[3:]
    _wait_exit(pid)
    try:
        os.remove(lock)                     # 旧实例异常退出时可能留下锁文件
    except OSError:
        pass
    time.sleep(0.2)
    try:
        subprocess.Popen(cmd, cwd=cwd or None, close_fds=True, creationflags=FLAGS)
    except Exception:  # noqa: BLE001
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
