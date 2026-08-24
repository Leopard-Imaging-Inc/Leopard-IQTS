"""全局样式（QSS）：浅色底 + 青色主色，贴近 assets/简化版图像分析软件 GUI 界面.jpeg。"""

APP_QSS = """
/* ---------- 全局 ---------- */
QWidget {
    background: #f5f7f9;
    color: #2b2f33;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow, QStatusBar {
    background: #ffffff;
}
QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #e2e6ea;
    padding: 2px;
}
QMenuBar::item {
    padding: 4px 10px;
    background: transparent;
}
QMenuBar::item:selected {
    background: #e8f4f5;
    border-radius: 4px;
}
QMenu {
    background: #ffffff;
    border: 1px solid #d5dbe0;
}
QMenu::item {
    padding: 6px 24px;
}
QMenu::item:selected {
    background: #e8f4f5;
}
QToolTip {
    background: #2b2f33;
    color: #ffffff;
    border: none;
    padding: 4px 8px;
}

/* ---------- 品牌栏 ---------- */
#brandBar {
    background: #ffffff;
    border-bottom: 1px solid #e2e6ea;
}
#brandLogo {
    font-size: 20px;
    font-weight: 700;
    color: #1b9aaa;
}
#brandSep {
    color: #d5dbe0;
    max-width: 1px;
    margin: 6px 4px;
}
#brandButton {
    background: transparent;
    border: none;
    font-size: 15px;
    font-weight: 600;
    color: #2b2f33;
    padding: 6px 12px;
}
#brandButton:hover {
    background: #e8f4f5;
    border-radius: 6px;
}
#brandButtonActive {
    background: transparent;
    border: none;
    border-bottom: 3px solid #1b9aaa;
    font-size: 15px;
    font-weight: 700;
    color: #17808e;
    padding: 6px 12px;
}

/* ---------- 左：Workflow 步骤栏 ---------- */
#workflowPanel {
    background: #ffffff;
    border-right: 1px solid #e2e6ea;
}
#workflowTitle {
    font-size: 18px;
    font-weight: 700;
}
#stepBadge, #stepBadgeNext {
    min-width: 22px; max-width: 22px;
    min-height: 22px; max-height: 22px;
    border-radius: 11px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
#stepBadge {
    background: #1b9aaa;
    color: #ffffff;
}
#stepBadgeNext {
    background: #2bb673;
    color: #ffffff;
}
#stepTitle, #stepTitleNext {
    font-size: 15px;
    font-weight: 700;
}
#stepTitle { color: #1b9aaa; }
#stepTitleNext { color: #2bb673; }
#stepStatus {
    color: #8a939b;
    margin-left: 30px;
}
/* 非当前步骤置灰（dim 动态属性由 WorkflowPanel.set_active_step 维护） */
#stepBadge[dim="true"], #stepBadgeNext[dim="true"] {
    background: #c9d1d7;
}
#stepTitle[dim="true"], #stepTitleNext[dim="true"] {
    color: #a7b0b7;
}
#stepStatus[dim="true"] {
    color: #c3cad0;
}
/* 步骤可点击：悬停加深提示 */
#stepTitle:hover { color: #12616c; }
#stepTitleNext:hover { color: #1e8a57; }
#stepTitle[dim="true"]:hover, #stepTitleNext[dim="true"]:hover {
    color: #6d767e;
}

/* ---------- 通用按钮 ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #c9d1d7;
    border-radius: 4px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #eef4f5; }
QPushButton:disabled {
    color: #a7b0b7;
    background: #f0f2f4;
    border-color: #dde3e7;
}
#primaryButton, #analyzeButton {
    background: #1b9aaa;
    border: 1px solid #17808e;
    color: #ffffff;
}
#primaryButton:hover, #analyzeButton:hover { background: #17808e; }
#primaryButton:disabled, #analyzeButton:disabled {
    background: #9fd3da;
    border-color: #9fd3da;
    color: #f2fafa;
}
/* 模式切换按钮：选中态高亮（互斥，同一时刻只有一个有颜色） */
QPushButton:checked {
    background: #1b9aaa;
    border: 1px solid #17808e;
    color: #ffffff;
}
QPushButton:checked:hover { background: #17808e; }
QPushButton:checked:disabled {
    background: #9fd3da;
    border-color: #9fd3da;
    color: #f2fafa;
}

/* ---------- 右：Source images ---------- */
#sourceArea { background: #f5f7f9; }
#sourceTitle {
    font-size: 18px;
    font-weight: 700;
}
#imagesTab {
    background: #ffffff;
    border: 1px solid #d5dbe0;
    border-bottom: 2px solid #1b9aaa;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: #17808e;
    font-weight: 700;
    padding: 6px 16px;
}
#dropZone {
    background: #ffffff;
    border: 2px dashed #1b9aaa;
    border-radius: 10px;
}
#dropHint {
    font-size: 20px;
    color: #6d767e;
}
#dropOr {
    color: #a7b0b7;
}
QScrollArea { background: #ffffff; border: 2px dashed #c9d1d7; border-radius: 10px; }

/* ---------- 单选框 ---------- */
QRadioButton { spacing: 6px; background: transparent; }
QRadioButton::indicator {
    width: 14px; height: 14px;
    border-radius: 8px;
    border: 2px solid #8a939b;
    background: #ffffff;
}
QRadioButton::indicator:checked {
    border-color: #1b9aaa;
    background: #1b9aaa;
}
QRadioButton::indicator:disabled {
    border-color: #d5dbe0;
    background: #f0f2f4;
}

/* ---------- 缩略图卡片 ---------- */
#thumbCard {
    background: #ffffff;
    border: 1px solid #d5dbe0;
    border-radius: 6px;
}
#thumbCard:hover { border-color: #1b9aaa; }
#thumbImage {
    background: #eef1f3;
    border-radius: 4px;
    color: #8a939b;
}
#thumbName { color: #4a5259; }

/* ---------- 分析选择对话框 / 面板 ---------- */
#panelTitle {
    font-size: 16px;
    font-weight: 700;
    color: #17808e;
}
#panelDesc {
    color: #8a939b;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #d5dbe0;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #4a5259;
}
#moduleList {
    background: #ffffff;
    border: 1px solid #d5dbe0;
    border-radius: 6px;
    outline: none;
}
#moduleList::item {
    padding: 8px 10px;
}
#moduleList::item:selected {
    background: #e8f4f5;
    color: #17808e;
}
QDialog { background: #f5f7f9; }
QTableWidget {
    background: #ffffff;
    border: 1px solid #d5dbe0;
    gridline-color: #eef1f3;
}
QHeaderView::section {
    background: #eef4f5;
    border: none;
    padding: 6px 8px;
    font-weight: 700;
    color: #4a5259;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #c9d1d7;
    border-radius: 4px;
    padding: 4px 6px;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1b9aaa;
}
"""
