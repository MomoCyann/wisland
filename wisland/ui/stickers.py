# -*- coding: utf-8 -*-
"""用户贴纸目录与按目标尺寸解码。"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui

from ..core.config import ROOT, cfg, expand

_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def sticker_dir() -> Path:
    raw = expand(cfg.get("island.sticker_dir", "march7stickers") or "march7stickers")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def sticker_paths() -> list[Path]:
    p = sticker_dir()
    try:
        return sorted((x for x in p.iterdir() if x.is_file() and x.suffix.lower() in _EXTS),
                      key=lambda x: x.name.lower())
    except OSError:
        return []


def load_sticker(path: Path, size: int) -> QtGui.QPixmap | None:
    reader = QtGui.QImageReader(str(path))
    reader.setAutoTransform(True)
    reader.setScaledSize(QtCore.QSize(size, size))
    img = reader.read()
    return None if img.isNull() else QtGui.QPixmap.fromImage(img)
