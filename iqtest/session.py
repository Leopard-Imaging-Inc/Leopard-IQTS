"""测试会话：管理已加载图像集与各模块分析状态。

M1 仅实现图像集管理（增删、清空、去重）；
各模块结果与 criteria 状态在 M2/M3 接入。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

#: 首版支持的图像扩展名（RAW 二进制仅登记路径，缩略图留待 M2 接入算法库解析）
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
    ".raw", ".dng",
}

#: QImageReader 可直接解码出缩略图的扩展名
THUMBNAILABLE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
}


@dataclass(frozen=True)
class ImageEntry:
    """一张源图像的会话记录。"""

    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def thumbnailable(self) -> bool:
        return self.path.suffix.lower() in THUMBNAILABLE_EXTENSIONS


class Session(QObject):
    """一轮测试会话：图像集 + 已选分析项配置 + 各模块结果（M3+）。"""

    images_changed = Signal()
    analyses_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.images: list[ImageEntry] = []
        #: 已选分析项：{module_key: {"params": {...}, "criteria": {...}}}
        self.analyses: dict[str, dict] = {}

    # ------------------------------------------------------------------ 图像集

    def add_images(self, paths: list[Path]) -> int:
        """加入图像路径（去重，按传入顺序）。返回实际新增数量。"""
        known = {e.path for e in self.images}
        added = 0
        for p in paths:
            p = Path(p)
            if p.suffix.lower() not in IMAGE_EXTENSIONS or p in known:
                continue
            self.images.append(ImageEntry(path=p))
            known.add(p)
            added += 1
        if added:
            self.images_changed.emit()
        return added

    def remove_image(self, path: Path) -> None:
        before = len(self.images)
        self.images = [e for e in self.images if e.path != path]
        if len(self.images) != before:
            self.images_changed.emit()

    def clear(self) -> None:
        changed_images = bool(self.images)
        if changed_images:
            self.images.clear()
            self.images_changed.emit()
        if self.analyses:
            self.analyses.clear()
            self.analyses_changed.emit()

    @property
    def count(self) -> int:
        return len(self.images)

    # --------------------------------------------------------------- 分析项

    def set_analyses(self, configs: dict) -> None:
        """替换已选分析项配置（② Select Analysis 对话框确认结果）。"""
        self.analyses = dict(configs)
        self.analyses_changed.emit()

    def merge_analyses(self, modules: dict) -> None:
        """将外部配置（JSON 读取）合并进已选分析项；未选的模块会被加入。"""
        for key, cfg in modules.items():
            if not isinstance(cfg, dict):
                continue
            target = self.analyses.setdefault(
                key, {"params": {}, "criteria": {}}
            )
            for section in ("params", "criteria"):
                values = cfg.get(section)
                if isinstance(values, dict):
                    target.setdefault(section, {}).update(values)
        if modules:
            self.analyses_changed.emit()


def scan_folder(folder: Path) -> list[Path]:
    """扫描文件夹（含子目录）中全部支持的图像文件，按文件名排序。"""
    folder = Path(folder)
    found = [
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(found, key=lambda p: p.name.lower())
