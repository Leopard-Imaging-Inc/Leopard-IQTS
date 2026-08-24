"""主窗口：Workflow 向导式布局（左步骤栏 + 右工作区双页）。

交互（按用户确认的 Workflow 设计）：
  - 顶部：菜单栏（File / JSON / Help）+ 品牌栏（logo+Leopard │ Analyze（默认选中）│ ⚙ Settings │ 🛠 Utilities）
  - 左侧 Workflow：① Select Images → ② Select Analysis（下方显示已选测试内容）
  - NEXT / PREVIOUS：在 ①② 之间切换，右侧工作区随之在
    Source images 页与 Analysis options 页之间切换
  - ANALYZE：QThread 运行所选分析；CLOSE FIGURES 一键关闭结果窗
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iqtest import __version__
from iqtest.config import store
import iqtest.analysis  # noqa: F401  # M3：注册真实算法进 runner.MODULE_ANALYZERS
from iqtest.figures.base_figure import FigureManager
from iqtest.figures.mtf_figure import MtfResultView
from iqtest.panels import module_title
from iqtest.panels.analysis_options import AnalysisOptionsWidget
from iqtest.runner import AnalysisRunner
from iqtest.session import Session
from iqtest.widgets.free_stack import FreeStackedWidget
from iqtest.widgets.source_images import SourceImagesWidget

WINDOW_TITLE = "LeopardIQTS — 图像质量分析"

LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "leopard-logo.jpg"


def app_icon() -> QIcon:
    """软件/窗口显示图标（未找到资源时回退到空图标，不影响启动）。"""
    if LOGO_PATH.is_file():
        return QIcon(str(LOGO_PATH))
    return QIcon()

def app_logo_pixmap(size: int = 24) -> QPixmap | None:
    """品牌栏 logo 位图（未找到资源时返回 None）。"""
    if not LOGO_PATH.is_file():
        return None
    pixmap = QPixmap(str(LOGO_PATH))
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class WorkflowPanel(QFrame):
    """左侧 Workflow 步骤栏（步骤标题可点击切换，与 NEXT/PREVIOUS 等效）。"""

    step_clicked = Signal(int)  # 0 = ① Select Images, 1 = ② Select Analysis

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("workflowPanel")
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)

        title = QLabel("Workflow")
        title.setObjectName("workflowTitle")

        # 步骤 ①
        self.step1_badge = QLabel("1")
        self.step1_badge.setObjectName("stepBadge")
        self.step1_title = QLabel("Select Images")
        self.step1_title.setObjectName("stepTitle")
        self.step1_status = QLabel("No images selected")
        self.step1_status.setObjectName("stepStatus")

        step1_head = QHBoxLayout()
        step1_head.setSpacing(8)
        step1_head.addWidget(self.step1_badge)
        step1_head.addWidget(self.step1_title)
        step1_head.addStretch(1)

        # 步骤 ②（Analysis options 页，NEXT / PREVIOUS 切换）
        self.step2_badge = QLabel("2")
        self.step2_badge.setObjectName("stepBadgeNext")
        self.step2_title = QLabel("Select Analysis")
        self.step2_title.setObjectName("stepTitleNext")
        self.step2_status = QLabel("Not selected")
        self.step2_status.setObjectName("stepStatus")
        self.step2_status.setWordWrap(True)

        step2_head = QHBoxLayout()
        step2_head.setSpacing(8)
        step2_head.addWidget(self.step2_badge)
        step2_head.addWidget(self.step2_title)
        step2_head.addStretch(1)

        # 操作按钮
        self.btn_next = QPushButton("NEXT")
        self.btn_next.setToolTip("切换到 ② Select Analysis（再次点击返回 ①）")
        self.btn_analyze = QPushButton("ANALYZE")
        self.btn_analyze.setObjectName("analyzeButton")
        self.btn_start_new = QPushButton("↻  START NEW ANALYSIS")
        self.btn_close_figures = QPushButton("⊞  CLOSE FIGURES")
        self.btn_close_figures.setToolTip("关闭全部结果 Figure 窗口")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.btn_next)
        btn_row.addWidget(self.btn_analyze)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addLayout(step1_head)
        layout.addWidget(self.step1_status)
        layout.addSpacing(12)
        layout.addLayout(step2_head)
        layout.addWidget(self.step2_status)
        layout.addSpacing(16)
        layout.addLayout(btn_row)
        layout.addSpacing(8)
        layout.addWidget(self.btn_start_new)
        layout.addWidget(self.btn_close_figures)
        layout.addStretch(1)

        session.images_changed.connect(self._refresh)
        session.analyses_changed.connect(self._refresh)

        # 步骤标题 / 徽章 / 状态均可点击切换步骤
        self._step_widgets = (
            (self.step1_badge, self.step1_title, self.step1_status),
            (self.step2_badge, self.step2_title, self.step2_status),
        )
        for group in self._step_widgets:
            for w in group:
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                w.installEventFilter(self)

        self._refresh()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease:
            for i, group in enumerate(self._step_widgets):
                if obj in group:
                    self.step_clicked.emit(i)
                    return True
        return super().eventFilter(obj, event)

    def _refresh(self) -> None:
        n = self.session.count
        self.step1_status.setText(
            "No images selected" if n == 0 else f"{n} image(s) selected"
        )
        if self.session.analyses:
            names = "、".join(module_title(k) for k in self.session.analyses)
            self.step2_status.setText(names)
        else:
            self.step2_status.setText("Not selected")

    def set_active_step(self, step: int) -> None:
        """高亮当前步骤（0=Select Images，1=Select Analysis），另一步骤置灰。"""
        groups = (
            (self.step1_badge, self.step1_title, self.step1_status),
            (self.step2_badge, self.step2_title, self.step2_status),
        )
        for i, widgets in enumerate(groups):
            for w in widgets:
                w.setProperty("dim", i != step)
                w.style().unpolish(w)
                w.style().polish(w)


class MainWindow(QMainWindow):
    """LeopardIQTS 主窗口。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)  # 允许自由缩放，仅保留一个体面的下限

        self.session = Session(self)

        self.figure_manager = FigureManager(self)
        self.figure_manager.register_view("mtf", MtfResultView)
        self.runner = AnalysisRunner(self)
        self._run_errors: dict[str, str] = {}
        self._compare_dialog = None  # MTF 模组比较对话框（非模态，单实例）
        self.runner.module_finished.connect(self._on_module_finished)
        self.runner.module_error.connect(self._on_module_error)
        self.runner.all_finished.connect(self._on_all_finished)

        self.workflow = WorkflowPanel(self.session)
        self.source_images = SourceImagesWidget(self.session)
        self.source_images.status_message.connect(
            lambda msg: self.statusBar().showMessage(msg, 5000)
        )
        self.analysis_options = AnalysisOptionsWidget(session=self.session)
        self.analysis_options.selection_changed.connect(
            self._on_analysis_selection_changed
        )
        self._step = 0  # 0 = ① Select Images, 1 = ② Select Analysis

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.workflow)
        splitter.addWidget(self._build_right_area())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_brand_bar())
        central_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        self._build_menus()
        self._connect_workflow_actions()
        self._set_step(0)
        self.statusBar().showMessage("就绪 — 拖拽图像文件到右侧区域开始", 8000)

    # ------------------------------------------------------------ 区域组装

    def _build_brand_bar(self) -> QWidget:
        """品牌栏：logo+Leopard │ Analyze │ ⚙ Settings │ 🛠 Utilities"""
        bar = QFrame()
        bar.setObjectName("brandBar")

        logo = QHBoxLayout()
        logo.setContentsMargins(4, 0, 4, 0)
        logo.setSpacing(8)
        logo_pm = app_logo_pixmap()
        if logo_pm is not None:
            logo_icon = QLabel()
            logo_icon.setObjectName("brandLogoIcon")
            logo_icon.setPixmap(logo_pm)
            logo.addWidget(logo_icon)
        logo_text = QLabel("Leopard")
        logo_text.setObjectName("brandLogo")
        logo.addWidget(logo_text)

        logo_widget = QWidget()
        logo_widget.setLayout(logo)

        sep1 = QFrame()
        sep1.setObjectName("brandSep")
        sep1.setFrameShape(QFrame.Shape.VLine)

        sep2 = QFrame()
        sep2.setObjectName("brandSep")
        sep2.setFrameShape(QFrame.Shape.VLine)

        # Analyze 是默认选中的工作流标签（无下拉菜单）
        self.btn_analyze_tab = QToolButton()
        self.btn_analyze_tab.setText("📈  Analyze")
        self.btn_analyze_tab.setObjectName("brandButtonActive")

        self.btn_settings_menu = QToolButton()
        self.btn_settings_menu.setText("⚙  Settings")
        self.btn_settings_menu.setObjectName("brandButton")
        self.btn_settings_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_menu = QMenu(self)
        for text in ("RAW 解析参数…（M2）", "CFA 默认 pattern…（M2）", "加速开关…（M2）"):
            action = settings_menu.addAction(text)
            action.setEnabled(False)
        self.btn_settings_menu.setMenu(settings_menu)

        self.btn_utilities_menu = QToolButton()
        self.btn_utilities_menu.setText("🛠  Utilities")
        self.btn_utilities_menu.setObjectName("brandButton")
        self.btn_utilities_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        utilities_menu = QMenu(self)
        read_raw_action = utilities_menu.addAction("Generalized Read Raw…")
        read_raw_action.triggered.connect(self._on_read_raw_dialog)
        compare_action = utilities_menu.addAction("MTF 模组比较…")
        compare_action.triggered.connect(self._on_mtf_compare_dialog)
        utilities_menu.addSeparator()
        for text in ("导出报告…（M4）", "批量分析…（后续迭代）", "Imatest JSON 导入（FOV，M3）"):
            action = utilities_menu.addAction(text)
            action.setEnabled(False)
        self.btn_utilities_menu.setMenu(utilities_menu)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(12)
        layout.addWidget(logo_widget)
        layout.addWidget(sep1)
        layout.addWidget(self.btn_analyze_tab)
        layout.addWidget(self.btn_settings_menu)
        layout.addStretch(1)
        layout.addWidget(sep2)
        layout.addWidget(self.btn_utilities_menu)
        return bar

    def _build_right_area(self) -> QWidget:
        area = QWidget()
        area.setObjectName("sourceArea")
        self._right_title = QLabel("Source images")
        self._right_title.setObjectName("sourceTitle")

        self._right_stack = FreeStackedWidget()
        self._right_stack.addWidget(self.source_images)      # 页 0：① Select Images
        self._right_stack.addWidget(self.analysis_options)   # 页 1：② Select Analysis

        layout = QVBoxLayout(area)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(self._right_title)
        layout.addWidget(self._right_stack, stretch=1)
        return area

    # ------------------------------------------------------------ 菜单

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("File(&F)")
        self._add_action(file_menu, "打开会话…（M4）", enabled=False)
        self._add_action(file_menu, "保存会话…（M4）", enabled=False)
        file_menu.addSeparator()
        self._add_action(file_menu, "导出报告 PDF…（M4）", enabled=False)
        self._add_action(file_menu, "导出结果 CSV…（M4）", enabled=False)
        file_menu.addSeparator()
        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        json_menu = bar.addMenu("JSON(&J)")
        load_action = QAction("读取 criteria 配置 (JSON)…(&O)", self)
        load_action.triggered.connect(self._on_load_criteria)
        json_menu.addAction(load_action)
        save_action = QAction("保存 criteria 配置 (JSON)…(&S)", self)
        save_action.triggered.connect(self._on_save_criteria)
        json_menu.addAction(save_action)
        json_menu.addSeparator()
        reset_action = QAction("恢复默认 criteria(&R)", self)
        reset_action.triggered.connect(self._on_reset_criteria)
        json_menu.addAction(reset_action)

        help_menu = bar.addMenu("Help(&H)")
        about_action = QAction("关于 LeopardIQTS(&A)", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
        self._add_action(help_menu, "用户手册（M5）", enabled=False)

    def _add_action(self, menu: QMenu, text: str, enabled: bool = True) -> QAction:
        action = QAction(text, self)
        action.setEnabled(enabled)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------ 动作

    def _connect_workflow_actions(self) -> None:
        self.workflow.btn_next.clicked.connect(self._on_toggle_step)
        self.workflow.btn_analyze.clicked.connect(self._on_analyze)
        self.workflow.btn_start_new.clicked.connect(self._on_start_new)
        self.workflow.btn_close_figures.clicked.connect(self._on_close_figures)
        self.workflow.step_clicked.connect(self._set_step)

    # ------------------------------------------------------------ 步骤切换

    def _on_toggle_step(self) -> None:
        self._set_step(1 if self._step == 0 else 0)

    def _set_step(self, step: int) -> None:
        """切换 Workflow 步骤：右侧页面、NEXT/PREVIOUS 文案、步骤高亮联动。"""
        self._step = step
        self._right_stack.setCurrentIndex(step)
        self._right_title.setText(
            "Source images" if step == 0 else "Analysis options"
        )
        self.workflow.btn_next.setText("NEXT" if step == 0 else "PREVIOUS")
        self.workflow.set_active_step(step)

    def _on_analysis_selection_changed(self) -> None:
        self.session.set_analyses(self.analysis_options.selected_configs())

    # ------------------------------------------------------------ 分析执行

    def _on_analyze(self) -> None:
        if self.session.count == 0:
            self.statusBar().showMessage("请先在 ① Select Images 加载图像", 5000)
            if self._step != 0:
                self._set_step(0)
            return
        if self.runner.is_running:
            self.statusBar().showMessage("分析进行中，请稍候…", 5000)
            return
        # ANALYZE 时取 Analysis options 页的最新配置
        self.session.set_analyses(self.analysis_options.selected_configs())
        if not self.session.analyses:
            self.statusBar().showMessage(
                "请在 ② Select Analysis 勾选至少一个分析项", 5000
            )
            self._set_step(1)
            return
        images = [e.path for e in self.session.images]
        self._run_errors = {}
        self.workflow.btn_analyze.setEnabled(False)
        self.runner.run(images, self.session.analyses)
        self.statusBar().showMessage(
            f"分析开始：{len(self.session.analyses)} 个模块…", 5000
        )

    def _on_module_finished(self, key: str, result: dict) -> None:
        self.figure_manager.show_result(key, module_title(key), result)

    def _on_module_error(self, key: str, message: str) -> None:
        self._run_errors[key] = message

    def _on_all_finished(self) -> None:
        self.workflow.btn_analyze.setEnabled(True)
        if self._run_errors:
            detail = "\n".join(
                f"· {module_title(k)}：{v}" for k, v in self._run_errors.items()
            )
            QMessageBox.warning(self, "Analyze", f"以下模块分析失败：\n{detail}")
        self.statusBar().showMessage(
            f"分析完成：成功 {len(self.session.analyses) - len(self._run_errors)} 个，"
            f"失败 {len(self._run_errors)} 个",
            8000,
        )

    def _on_start_new(self) -> None:
        if self.session.count == 0 and not self.session.analyses:
            return
        ret = QMessageBox.question(
            self,
            "Start New Analysis",
            "将清空当前图像、已选分析项并关闭全部 Figure，开始新一轮测试。是否继续？",
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.figure_manager.close_all()
            self.session.clear()
            self.analysis_options.set_selected({})
            self._set_step(0)
            self.statusBar().showMessage("已开始新的分析会话", 5000)

    def _on_close_figures(self) -> None:
        n = self.figure_manager.close_all()
        self.statusBar().showMessage(
            f"已关闭 {n} 个 Figure 窗口" if n else "当前没有打开的 Figure 窗口",
            5000,
        )

    def _on_read_raw_dialog(self) -> None:
        """Utilities → Generalized Read Raw…：RAW 读取全局参数设置。"""
        from iqtest.widgets.read_raw_dialog import ReadRawDialog

        dialog = ReadRawDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.statusBar().showMessage(
                "Read Raw 设置已保存，读取 .raw 时全局生效", 8000
            )

    def _on_mtf_compare_dialog(self) -> None:
        """Utilities → MTF 模组比较…：两份 MTF 结果 CSV 的 A/B 比较。"""
        from iqtest.panels.mtf_compare_panel import MtfCompareDialog

        if self._compare_dialog is not None:
            try:
                self._compare_dialog.raise_()
                self._compare_dialog.activateWindow()
                return
            except RuntimeError:  # 对话框已被销毁（WA_DeleteOnClose）
                self._compare_dialog = None
        self._compare_dialog = MtfCompareDialog(self)
        self._compare_dialog.compared.connect(
            lambda result: self.statusBar().showMessage(
                f"MTF 模组比较完成：{result['main_summary']}", 10000
            )
        )
        self._compare_dialog.show()

    # ------------------------------------------------------------ JSON 持久化

    def _current_modules_config(self) -> dict:
        """当前生效的模块配置 = 默认配置 ∪ 已选分析项（已选覆盖默认）。"""
        return store.merge_modules_config(
            store.default_modules_config(), self.session.analyses
        )

    def _on_save_criteria(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 criteria 配置", "criteria.json", "JSON 配置 (*.json)"
        )
        if not path:
            return
        try:
            store.save_json(path, {"modules": self._current_modules_config()})
        except OSError as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.statusBar().showMessage(f"criteria 配置已保存：{path}", 8000)

    def _on_load_criteria(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "读取 criteria 配置", "", "JSON 配置 (*.json)"
        )
        if not path:
            return
        try:
            data = store.load_json(path)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "读取失败", str(e))
            return
        self.session.merge_analyses(data["modules"])
        self.analysis_options.set_selected(self.session.analyses)
        self.statusBar().showMessage(
            f"已载入 {len(data['modules'])} 个模块的 criteria 配置：{path}", 8000
        )

    def _on_reset_criteria(self) -> None:
        if not self.session.analyses:
            self.statusBar().showMessage(
                "尚未选择分析项；Analysis options 页默认即为默认 criteria", 5000
            )
            return
        defaults = store.default_modules_config()
        for key in self.session.analyses:
            if key in defaults:
                self.session.analyses[key] = defaults[key]
        self.analysis_options.set_selected(self.session.analyses)
        self.statusBar().showMessage("已恢复默认 criteria", 5000)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 LeopardIQTS",
            f"<b>LeopardIQTS</b> v{__version__} 基于 LeopardiQ 算法库的镜头图像质量（IQ）评估软件。<br>"
            "当前版本：初步实现 MTF/SFR 配套功能。<br>"
            "待实现功能：Lens Shading / Color / Flare / FOV。",
        )
