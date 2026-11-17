# -*- coding: utf-8 -*-
"""网易云音乐播放状态：读取本地日志 cloudmusic.elog（无需插件、无需开启 SMTC）。

网易云 PC 版 3.x 默认不向 Windows 系统媒体控件（SMTC）报告播放信息；即使在设置里打开「开启SMTC」，
也不提供播放进度。但它会把播放事件写进 %LOCALAPPDATA%\\NetEase\\CloudMusic\\cloudmusic.elog：
  - "checkPlayPrivilege" / "playOneTrackInPlayingList"  当前歌曲（id / 歌名 / 歌手 / 专辑 / 时长 / 封面）
  - "native播放资源load完成"                              真正开始出声
  - "setPlayingPosition", 秒                             拖动进度条后的位置
  - "native播放state", 1|2                               1 = 播放，2 = 暂停
日志是逐字节替换编码的（解码公式来自社区项目 netease-cloudmusic-detector，MIT）。

只解析歌名 / 歌手 / 专辑 / 时长 / 歌曲 id / 封面 / 进度；日志里带签名的播放地址不会被读取或保存。
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import threading
import time
import traceback

import psutil

from wisland.core.bg import http_client, run_bg

ELOG = os.path.expandvars(r"%LOCALAPPDATA%\NetEase\CloudMusic\cloudmusic.elog")
PRELOAD_BYTES = 2 * 1024 * 1024     # 回看最近约 2MB 日志即可覆盖数十首歌的当前曲目与红心状态
MAX_CARRY = 256 * 1024

# 网易云重启后恢复播放时只写 appRestore{"id":…,"pause":true}，不带歌名，日志里也
# 还没出现过这首歌的详情；此时按 song_id 查一次公开接口补上标题/歌手/专辑/时长/封面。
META_API = "https://music.163.com/api/song/detail"
META_HEADERS = {"Referer": "https://music.163.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
META_RETRY_S = 60.0

# 解码表：密文字节 -> 明文字节
_TABLE = bytes(((((b >> 4) ^ (((b & 15) + 8) % 16)) % 16) * 16 + (b >> 6) * 4 + ((~(b >> 4)) & 3)) & 0xFF
               for b in range(256))
_INV = bytearray(256)
for _b in range(256):
    _INV[_TABLE[_b]] = _b
NEWLINE = _INV[0x0A]                 # 日志里的换行也是编码过的

_HEADER = re.compile(r"^\[(\d+):(\d+):(\d{4}/\d{6}):(\d+):([A-Z]+):")
_SEEK = re.compile(r'"setPlayingPosition"\s*,\s*(-?\d+(?:\.\d+)?)')
_STATE = re.compile(r'"native[^"]*state"\s*,\s*(\d+)')
_EXIT = re.compile(r"Process\s+(\d+)\s+exited")
_LIKE_CHANGE = re.compile(r'"op"\s*:\s*"(add_track|del_track)".{0,600}?"ids"\s*:\s*\[\s*(\d+)')
_MODE_SWITCH = re.compile(r'"播放模式切换"\s*,\s*"旧播放模式::"\s*,\s*"([^"]*)"\s*,\s*"新播放模式::"\s*,\s*"([^"]*)"')
_DAWN_MODE = re.compile(r'"mode"\s*:\s*"(playFm|ai)"')

_k32 = ctypes.WinDLL("kernel32")
_k32.GetTickCount64.restype = ctypes.c_ulonglong


def _event_mono(tick_ms: int) -> float:
    """日志头里的时间戳是开机以来的毫秒数（GetTickCount），换算成 time.monotonic()。"""
    return time.monotonic() - max(0.0, (_k32.GetTickCount64() - tick_ms) / 1000.0)


def _json(line: str):
    a, b = line.find("{"), line.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(line[a:b + 1])
    except ValueError:
        return None


def _track(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    t = data.get("track") if isinstance(data.get("track"), dict) else data
    if not t.get("id"):
        return None
    album = t.get("album") if isinstance(t.get("album"), dict) else {}
    artists = t.get("artists") if isinstance(t.get("artists"), list) else []
    return {
        "id": str(t["id"]),
        "title": str(t.get("name") or ""),
        "artist": " / ".join(str(a.get("name")) for a in artists if isinstance(a, dict) and a.get("name")),
        "album": str(album.get("name") or ""),
        "duration": (float(t.get("duration") or 0) / 1000.0),
        "cover": str(album.get("picUrl") or ""),
    }


class NeteaseLog:
    """在媒体线程里定期调用 poll()；snapshot() 返回当前播放状态（没有在播的网易云时为 None）。"""

    def __init__(self, path: str = ELOG):
        self.path = path
        self._lock = threading.Lock()
        self._offset = -1
        self._carry = b""
        # 元数据缓存跨 _reset() 保留：进程重启恢复播放时靠它把歌名补回来
        self._meta: dict[str, dict] = {}
        self._meta_pending: set[str] = set()
        self._meta_failed: dict[str, float] = {}
        self._meta_lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.track: dict | None = None
        self.playing = False
        self.liked: bool | None = None
        self.play_mode: str = ""
        self._ai_expect_until = 0.0
        self._liked_by_id: dict[str, bool] = {}
        self._tray_song_id = ""       # 切歌后短时间内，trayLike 图标对应的新歌曲
        self._tray_from_tick = 0
        self._tray_until_tick = 0
        self._hint_title = ""
        self._hint_artist = ""
        self._hint_thumb = ""
        self._hint_tick = 0
        self._hint_liked: bool | None = None
        self._hint_liked_tick = 0
        self._stub_since = 0.0
        self._last_good_snap: dict | None = None
        self.pos = 0.0              # 暂停时的位置；播放时为 anchor 时刻的位置
        self.anchor = 0.0           # 播放中：位置 = pos + (now - anchor)
        self.anchored = False
        self.pid = 0

    # ---------------- 读取 ----------------
    def poll(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            self._offset = -1
            self._reset()
            return
        with self._lock:
            if self._offset < 0 or size < self._offset:          # 首次 / 日志被重建
                self._reset()
                start = max(0, size - PRELOAD_BYTES)
                self._carry = b""
                self._read(start, size, skip_partial=start > 0)
            elif size > self._offset:
                self._read(self._offset, size)
            self._offset = size

    def _read(self, start: int, end: int, skip_partial: bool = False):
        try:
            with open(self.path, "rb") as f:
                f.seek(start)
                buf = f.read(end - start)
        except OSError:
            return
        if skip_partial:                          # 从中间开始读：丢掉第一段不完整的行
            i = buf.find(bytes([NEWLINE]))
            buf = buf[i + 1:] if i >= 0 else b""
        buf = self._carry + buf
        cut = buf.rfind(bytes([NEWLINE]))
        if cut < 0:
            self._carry = buf[-MAX_CARRY:]
            return
        self._carry = buf[cut + 1:][-MAX_CARRY:]
        text = buf[:cut + 1].translate(_TABLE).decode("utf-8", "replace")
        for line in text.split("\n"):
            self._line(line)

    # ---------------- 状态机 ----------------
    def _now_pos(self, at: float) -> float:
        return self.pos + max(0.0, at - self.anchor) if self.playing else self.pos

    def _update_liked(self, line: str):
        """恢复红心状态。

        日志字段 ``is_heart`` 表示心动模式来源，不是歌曲是否已收藏；它在空心歌曲上
        也会持续写 1，不能用于红心 UI。真正可靠的是切歌后紧跟的 trayLike 图标，
        以及用户操作产生、带歌曲 id 的 add_track / del_track 事件。
        """
        plain = line.replace('\\"', '"')
        change = _LIKE_CHANGE.search(plain)
        if change:
            liked = change.group(1) == "add_track"
            sid = change.group(2)
            self._liked_by_id[sid] = liked
            if self.track and self.track.get("id") == sid:
                self.liked = liked

        if '"id":"trayLike"' not in plain:
            return
        liked = "/liked.svg" in plain
        if not liked and "/like.svg" not in plain:
            return
        header = _HEADER.match(line)
        if not header:
            return
        tick = int(header.group(4))
        self._hint_liked = liked
        self._hint_liked_tick = tick
        if not self.track:
            return
        sid = str(self.track.get("id") or "")
        if sid == self._tray_song_id and self._tray_from_tick <= tick <= self._tray_until_tick:
            self.liked = liked
            self._liked_by_id[sid] = liked
            self._hint_liked = None

    def _init_liked_for_track(self, sid: str, tick: int):
        """切歌时初始化红心状态；若伴随切歌预告已紧邻写出 trayLike，则直接采纳，否则重置为空心。"""
        liked = False
        if (
            self._hint_liked is not None
            and 0 <= tick - self._hint_liked_tick <= 2500
            and abs(self._hint_liked_tick - self._hint_tick) <= 1200
        ):
            liked = self._hint_liked
            self._liked_by_id[sid] = liked
            self._hint_liked = None
        self.liked = liked
        self._tray_song_id = sid
        self._tray_from_tick, self._tray_until_tick = tick, tick + 2000

    def set_liked(self, song_id: str, liked: bool):
        """同步 Wisland 自己触发的红心操作，避免下一次轮询回滚即时反馈。"""
        sid = str(song_id or "")
        if not sid:
            return
        with self._lock:
            self._liked_by_id[sid] = bool(liked)
            if self.track and self.track.get("id") == sid:
                self.liked = bool(liked)

    def set_position(self, seconds: float):
        """同步 Wisland 自己触发的进度跳转，避免日志写出前的下一次轮询把进度拉回旧值。"""
        with self._lock:
            self.pos = max(0.0, float(seconds or 0.0))
            self.anchor = time.monotonic()
            self.anchored = True

    def set_play_mode(self, mode: str):
        """同步 Wisland 主动切换的播放模式（'fm' / 'ai'）。"""
        with self._lock:
            self.play_mode = str(mode or "")
            self._ai_expect_until = (time.monotonic() + 2.5) if self.play_mode == "ai" else 0.0

    @staticmethod
    def _norm_mode(raw: str) -> str:
        low = (raw or "").strip().lower()
        if low in ("playfm", "fm"):
            return "fm"
        if low in ("playai", "aimode", "ai"):
            return "ai"
        return "normal" if low else ""

    def _update_hints(self, line: str, tick: int):
        """提取 UpdateMenu / SMTCWrapper 中的歌名、歌手与本地封面路径。

        漫游模式（playFm）切歌时不写 playOneTrackInPlayingList / checkPlayPrivilege，
        但紧随切歌动作就会写出 UpdateMenu(openVinylPage) 和 SMTCWrapper；用它们即时
        补齐歌名、歌手和本地缩略图，可避免切歌瞬间掉回「未在播放」与空封面。
        """
        if '"menu_id":"openVinylPage"' in line:
            body_at = max(0, line.find("] "))
            a, b = line.find("[", body_at), line.rfind("]")
            if a >= 0 and b > a:
                try:
                    items = json.loads(line[a:b + 1])
                    item = next((x for x in items if isinstance(x, dict) and x.get("menu_id") == "openVinylPage"), None) if isinstance(items, list) else None
                    if item:
                        txt = str(item.get("text") or "").strip()
                        if txt:
                            t, sep, ar = txt.partition(" - ")
                            title, artist = (t.strip(), ar.strip()) if sep else (txt, "")
                            if (title, artist) != (self._hint_title, self._hint_artist):
                                self._hint_thumb = ""
                            self._hint_title, self._hint_artist, self._hint_tick = title, artist, tick
                            if self.track and abs(tick - self._hint_tick) <= 2500:
                                if not self.track.get("title") and title:
                                    self.track["title"] = title
                                if artist and len(artist) > len(self.track.get("artist") or ""):
                                    self.track["artist"] = artist
                except ValueError:
                    pass
            return

        if "[SMTCWrapper] SMTC title=" in line:
            body = line.split("[SMTCWrapper] SMTC title=", 1)[1]
            title, _sep, artist = body.rpartition(", artist=") if ", artist=" in body else (body, "", "")
            title, artist = title.strip(), artist.strip()
            if title:
                # UpdateMenu 通常带完整歌手列表（如 "A/B"），SMTC 只带第一歌手；尽量保留完整歌手
                if self._hint_title == title and self._hint_artist and self._hint_artist.startswith(artist):
                    artist = self._hint_artist
                elif (title, artist) != (self._hint_title, self._hint_artist):
                    self._hint_thumb = ""
                self._hint_title, self._hint_artist, self._hint_tick = title, artist, tick
                if self.track and not self.track.get("title"):
                    self.track["title"] = title
                    if artist and not self.track.get("artist"):
                        self.track["artist"] = artist
            return

        if "[SMTCWrapper] SMTC thumbnail=" in line:
            path = line.split("[SMTCWrapper] SMTC thumbnail=", 1)[1].strip()
            if path:
                self._hint_thumb = path
                if self.track:
                    self.track["cover_file"] = path

    def _line(self, line: str):
        self._update_liked(line)
        if not line.startswith("["):
            return
        if "[SMTCWrapper]" in line or '"menu_id":"openVinylPage"' in line:
            m = _HEADER.match(line)
            if m:
                self._update_hints(line, int(m.group(4)))
            return
        if "【playing】" not in line and "【fmPlaying】" not in line and "【曙光点位】" not in line and "exit" not in line:
            return
        m = _HEADER.match(line)
        if not m:
            return
        tick = int(m.group(4))
        pid, at = int(m.group(1)), _event_mono(tick)
        # 只有真正的退出事件才整块重置：网易云的托盘右键菜单 JSON 里同样带
        # {"menu_id":"exitApp"} 这一项，用 "exitApp" in line 判断会把「右键托盘」
        # 误当成退出，把已经同步的播放状态清空。真退出行带的是 "actionId":"exitApp"。
        if '"actionId":"exitApp"' in line:
            self._reset()
            return
        ex = _EXIT.search(line)
        if ex:
            if self.pid and int(ex.group(1)) == self.pid:
                self._reset()
            return
        if "【fmPlaying】" in line:
            if '"fmPlay"' in line:
                self.play_mode = "fm"
            return
        if "【曙光点位】" in line:
            dm = _DAWN_MODE.search(line)
            if dm and not self.play_mode:
                self.play_mode = self._norm_mode(dm.group(1))
            return
        ms = _MODE_SWITCH.search(line)
        if ms:
            nxt = self._norm_mode(ms.group(2))
            if nxt == "normal" and time.monotonic() < self._ai_expect_until:
                return
            self.play_mode = nxt
            return
        if '"心动模式开启成功"' in line:
            self._ai_expect_until = 0.0
            self.play_mode = "ai"
            return
        if '"jump2Track"' in line:
            self._hint_thumb = ""
            return
        if '"checkPlayPrivilege"' in line or '"playOneTrackInPlayingList"' in line:
            raw = _json(line)
            if isinstance(raw, dict) and raw.get("scene"):
                sc = self._norm_mode(str(raw.get("scene") or ""))
                if sc:
                    self.play_mode = sc
            t = _track(raw)
            if t and (self.track is None or t["id"] != self.track["id"]):
                self.track, self.pid = t, pid
                # 每次切歌先初始化红心（仅采纳紧随本次切歌预告写出的 trayLike），
                # 随后只由当前歌曲自己带 id 的 add_track / del_track 或 trayLike 事件继续同步。
                self._init_liked_for_track(t["id"], tick)
                self._stub_since = 0.0
                self.playing = '"playOneTrackInPlayingList"' in line
                self.pos, self.anchor, self.anchored = 0.0, at, False
            elif t and self.track:
                if not self.track.get("title"):
                    self.track.update({k: v for k, v in t.items() if v})
                else:
                    for k in ("album", "duration", "cover"):
                        if t.get(k) and not self.track.get(k):
                            self.track[k] = t[k]
            return
        sk = _SEEK.search(line)
        if sk:
            self.pos, self.anchor, self.anchored = max(0.0, float(sk.group(1))), at, True
            return
        stt = _STATE.search(line)
        if stt:
            cur = self._now_pos(at)
            self.playing = stt.group(1) == "1"
            self.pos, self.anchor, self.anchored = cur, at, True
            return
        if '"appRestore' in line:
            # 网易云重启后「播放信息恢复」只有 id / current / pause，没有歌名。
            # 不处理的话新实例起来后一直拿不到状态，直到用户点歌写出 playOneTrackInPlayingList。
            d = _json(line) or {}
            sid = str(d.get("id") or "")
            if sid and (self.track is None or sid != self.track["id"]):
                self.track = self._stub(sid)
                self.liked = False
                self._tray_song_id = sid
                self._tray_from_tick, self._tray_until_tick = tick, tick + 2000
                self._stub_since = time.monotonic()
                pos = float(d.get("current") or 0)
                self.playing = not bool(d.get("pause"))
                self.pos, self.anchor, self.anchored = pos, at, True
                self.pid = pid
                self._ensure_meta(sid)
            return
        if '"native' in line and "load" in line and ("开始load" in line or "完成" in line):
            d = _json(line) or {}
            sid = str(d.get("songId") or "")
            if not sid:
                return
            is_done = "完成" in line
            if self.track and sid == self.track["id"]:
                if is_done and self.playing and not self.anchored:
                    self.pos, self.anchor = 0.0, at          # 缓冲结束、真正出声：校正进度
            else:
                st = self._stub(sid)
                if tick - self._hint_tick <= 4000 and self._hint_title:
                    st["title"] = self._hint_title
                    st["artist"] = self._hint_artist
                    if self._hint_thumb:
                        st["cover_file"] = self._hint_thumb
                self.track = st
                self._init_liked_for_track(sid, tick)
                self._stub_since = time.monotonic()
                self.playing, self.pos, self.anchor, self.anchored, self.pid = True, 0.0, at, False, pid
                self._ensure_meta(sid)

    # ---------------- 元数据补齐 ----------------
    @staticmethod
    def _stub(sid: str) -> dict:
        return {"id": sid, "title": "", "artist": "", "album": "", "duration": 0.0, "cover": "", "cover_file": ""}

    def _apply_meta(self, sid: str, meta: dict):
        t = self.track
        if not t or t.get("id") != sid:
            return
        if not t.get("title") and meta.get("title"):
            t["title"] = meta["title"]
        if meta.get("artist") and (not t.get("artist") or len(meta["artist"]) > len(t.get("artist") or "")):
            t["artist"] = meta["artist"]
        for k in ("album", "duration", "cover"):
            if meta.get(k) and not t.get(k):
                t[k] = meta[k]

    def _ensure_meta(self, sid: str):
        """当前曲目没有标题时，按 id 补全元数据（命中缓存立即回填，否则后台取一次）。"""
        if not sid:
            return
        with self._meta_lock:
            known = self._meta.get(sid)
            if known is not None:
                self._apply_meta(sid, known)
                return
            if sid in self._meta_pending:
                return
            if time.monotonic() - self._meta_failed.get(sid, -1e9) < META_RETRY_S:
                return
            self._meta_pending.add(sid)
        run_bg(self._fetch_meta, sid,
               on_done=lambda res, sid=sid: self._meta_done(sid, res),
               on_error=lambda _e, sid=sid: self._meta_done(sid, None))

    def _meta_done(self, sid: str, res: dict | None):
        ok = bool(res and res.get("title"))
        with self._meta_lock:
            self._meta_pending.discard(sid)
            if ok:
                self._meta[sid] = res
                while len(self._meta) > 256:
                    self._meta.pop(next(iter(self._meta)))
                self._meta_failed.pop(sid, None)
            else:
                self._meta_failed[sid] = time.monotonic()
        if ok:
            with self._lock:
                self._apply_meta(sid, res)
                while len(self._liked_by_id) > 256:
                    self._liked_by_id.pop(next(iter(self._liked_by_id)))

    @staticmethod
    def _fetch_meta(sid: str) -> dict | None:
        try:
            r = http_client().get(META_API, params={"ids": f"[{sid}]"}, headers=META_HEADERS)
            r.raise_for_status()
            songs = (r.json() or {}).get("songs") or []
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return None
        if not songs:
            return None
        s = songs[0]
        # 这个接口用的是 songs[].artists / album / duration（毫秒），与 weapi 的 ar/al/dt 不同
        al = s.get("album") if isinstance(s.get("album"), dict) else {}
        ar = s.get("artists") if isinstance(s.get("artists"), list) else []
        return {
            "id": str(s.get("id") or sid),
            "title": str(s.get("name") or ""),
            "artist": " / ".join(str(a.get("name")) for a in ar if isinstance(a, dict) and a.get("name")),
            "album": str(al.get("name") or ""),
            "duration": float((s.get("duration") or 0) / 1000.0),
            "cover": str(al.get("picUrl") or ""),
        }

    # ---------------- 输出 ----------------
    def snapshot(self) -> dict | None:
        with self._lock:
            t = self.track
            if t and not (t.get("title") and t.get("duration") and t.get("cover")):
                self._ensure_meta(t["id"])      # 已在缓存里则立即回填
            if self.pid and not psutil.pid_exists(self.pid):
                self._reset()
                return None
            if not t:
                return None
            now = time.monotonic()
            if not t.get("title"):
                # 切歌后元数据尚未回填的短暂窗口内沿用上一帧快照，防止 UI 闪出「未在播放」与空封面
                if self._last_good_snap and now - self._stub_since < 2.5:
                    snap = dict(self._last_good_snap)
                    snap["stamp"] = now
                    snap["play_mode"] = self.play_mode
                    return snap
                return None
            pos = self._now_pos(now)
            if t["duration"]:
                pos = min(pos, t["duration"])
            sid = t["id"]
            meta_ready = bool(t.get("cover") or t.get("cover_file") or sid in self._meta or sid in self._meta_failed)
            snap = {"song_id": sid, "title": t["title"], "artist": t["artist"], "album": t["album"],
                    "duration": t["duration"], "cover": t["cover"], "cover_file": t.get("cover_file") or "",
                    "playing": self.playing, "liked": self.liked, "play_mode": self.play_mode,
                    "meta_ready": meta_ready, "position": pos, "stamp": now}
            self._last_good_snap = dict(snap)
            return snap
