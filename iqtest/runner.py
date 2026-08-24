"""分析调度：QThread worker 异步执行所选分析项（规划 §4.1「分析异步执行」）。

M2 提供调度框架 + stub 分析函数；M3 将各模块 analyze_* 注册进
MODULE_ANALYZERS 即可获得真实结果，调度层无需改动。

分析函数约定（与算法层统一接口一致）：
    fn(images: list[Path], config: dict) -> dict
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

AnalyzeFn = Callable[[list[Path], dict], dict]

#: M3 在此注册真实算法：MODULE_ANALYZERS["mtf"] = analyze_mtf_adapter …
MODULE_ANALYZERS: dict[str, AnalyzeFn] = {}


def stub_analyzer(images: list[Path], config: dict) -> dict:
    """M2 占位分析：不调用算法，返回结构化 stub 结果。"""
    return {
        "status": "STUB",
        "note": "算法接口将于 M3 接入（leopardiq analyze_*），当前为调度框架验证结果。",
        "n_images": len(images),
        "images": [p.name for p in images],
        "config": config,
    }


class _Worker(QObject):
    module_finished = Signal(str, dict)
    module_error = Signal(str, str)
    progress = Signal(int, int)
    finished = Signal()

    def __init__(
        self,
        images: list[Path],
        configs: dict,
        analyzers: dict[str, AnalyzeFn],
    ) -> None:
        super().__init__()
        self._images = images
        self._configs = configs
        self._analyzers = analyzers

    def run(self) -> None:
        total = len(self._configs)
        for i, (key, config) in enumerate(self._configs.items(), start=1):
            fn = self._analyzers.get(key, stub_analyzer)
            try:
                result = fn(self._images, config)
            except Exception as e:  # 算法报错不中断其余模块
                self.module_error.emit(key, f"{type(e).__name__}: {e}")
            else:
                self.module_finished.emit(key, result)
            self.progress.emit(i, total)
        self.finished.emit()


class AnalysisRunner(QObject):
    """一次 ANALYZE 执行：在 QThread 中依次运行所选模块。"""

    started = Signal(int)          # 模块总数
    module_finished = Signal(str, dict)
    module_error = Signal(str, str)
    progress = Signal(int, int)    # 已完成, 总数
    all_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def run(
        self,
        images: list[Path],
        configs: dict,
        analyzers: dict[str, AnalyzeFn] | None = None,
    ) -> bool:
        """启动分析；已有任务在跑或配置为空时返回 False。"""
        if self._thread is not None or not configs:
            return False

        thread = QThread(self)
        worker = _Worker(list(images), dict(configs), analyzers or MODULE_ANALYZERS)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.module_finished.connect(self.module_finished)
        worker.module_error.connect(self.module_error)
        worker.progress.connect(self.progress)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        self.started.emit(len(configs))
        thread.start()
        return True

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.all_finished.emit()
