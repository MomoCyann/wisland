# -*- coding: utf-8 -*-
"""页面布局：导航里显示哪些页面、按什么顺序。

配置写在 config.json → island.pages：[{"key": "home", "visible": true}, ...]
- 顺序即导航顺序；visible=false 的页面完全不加载到导航里（也不会跑它的定时器）
- 留空 / 缺项 = 该页面按代码顺序补到末尾并显示；全部隐藏时自动恢复第一个
"""
from __future__ import annotations

from ..core.config import cfg

# 页面元信息：key -> (标题, 图标, 一句话说明)。顺序 = 代码里的默认顺序。
PAGE_INFO: dict[str, tuple[str, str, str]] = {
    "home": ("主页", "\uE80F", "播放控制、快捷操作、应用启动器"),
    "msg": ("消息", "\uE8BD", "QQ / 微信 / 邮件 提醒与未读数"),
    "stock": ("股票", "\uEAFC", "A 股 / 港股 / 美股 行情与分时"),
    "weather": ("天气", "\uE753", "多城市天气、逐小时与 5 天预报"),
    "ctl": ("控制", "\uE9E9", "音量、亮度、WLAN / 蓝牙 / 热点、Clash Verge"),
    "clip": ("剪贴板", "\uE77F", "最近复制的 10 条文字 / 图片"),
    "trans": ("翻译", "\uF2B7", "翻译与实时字幕"),
    "tasks": ("窗口", "\uE7C4", "Alt-Tab 式窗口切换"),
    "perf": ("性能", "\uE9D9", "CPU / 内存 / 网络 / 磁盘监控"),
}


def page_layout(available: list[str]) -> list[dict]:
    """把配置规范成完整布局：[{key, visible}]，只含 available 里真实存在的页面。"""
    raw = cfg.get("island.pages")
    out: list[dict] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                k, vis = str(it.get("key") or ""), bool(it.get("visible", True))
            else:
                k, vis = str(it or ""), True
            if k in available and k not in seen:
                seen.add(k)
                out.append({"key": k, "visible": vis})
    for k in available:
        if k not in seen:
            out.append({"key": k, "visible": True})
    if out and not any(p["visible"] for p in out):
        out[0]["visible"] = True
    return out


def save_page_layout(layout: list[dict]):
    cfg.set("island.pages", [{"key": p["key"], "visible": bool(p["visible"])} for p in layout])


def page_title(key: str) -> str:
    return PAGE_INFO.get(key, (key, "", ""))[0]
