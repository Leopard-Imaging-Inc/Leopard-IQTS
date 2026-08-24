***

tags:

* project
  area: "\[\[工作]]"
  status: Doing
  created: 2026-07-22
  finished:
  comments: 自建的 IQ 测试软件， 用来评估新镜头。使用 LeopardIQ 库。
  archive: false

***

**主要功能**

1. 镜头MTF 的分布
2. Lens shading(chrom/lum, 几种光源)
3. Flare
4. 畸变
5. TV Distortion
6. FOV
7. Color 比例
8. HDR
9. chromatic aberration

***

## 与 NVIDIA DA-11028-001\_v1.1 EOL 测试项对比

> 参考文档：`DA-11028-001_v1.1` — NVIDIA Camera Testing Guidelines: End of Line Image Quality

### 一、NVIDIA 文档测试项总览

NVIDIA 的 EOL（End of Line）IQ 测试分为 **三大模块**，按测试流程顺序如下：

| 测试模块                       | 捕获条件                                   | 核心测试项                                                                                                                                                                                                             |
| -------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Darkfield Test（暗场测试）**   | 镜头盖黑盖，0 Lux，8× RAW 帧                   | Black Level、Defective Pixels/Clusters、Defective Rows/Columns、Fixed Pattern Noise (FPN)、Temporal Noise、DSNU                                                                                                        |
| **Brightfield Test（亮场测试）** | Opal 漫射板 / 积分球，5500K，≥600 lux，8× RAW 帧 | Center of Illumination、Relative Illumination（Lens Shading）、Color Uniformity、Lens Shading Correction、Hot/Cold Defective Pixels/Clusters/Rows/Columns、Fixed Pattern Noise、PRNU、Contamination（Particles & Blemishes） |
| **SFR Test（空间频率响应）**       | 斜边靶标（Collimator 或 Chart），1× RAW 帧      | SFR/MTF、SFR Uniformity（Lens Tilt）、SFR Falloff                                                                                                                                                                     |

### 二、逐项对比

| 本软件规划项                            | NVIDIA 文档对应项                                                 | 对齐情况         | 备注                                                                                                            |
| --------------------------------- | ------------------------------------------------------------ | ------------ | ------------------------------------------------------------------------------------------------------------- |
| 1. 镜头 MTF 的分布                     | **SFR Test → SFR/MTF**                                       | ✅ 对齐         | NVIDIA 使用 SFRMAT3 计算斜边 SFR；本软件直接评估 MTF，目标一致。                                                                  |
| 2. Lens shading (chrom/lum, 几种光源) | **Brightfield → Relative Illumination**                      | ⚠️ 部分对齐      | NVIDIA 的 Relative Illumination 仅评估亮度（luminance）shading，通过四象限最小值和差值量化；本软件还计划评估 **chrom shading** 和多光源条件，覆盖面更广。 |
| 3. Flare                          | —                                                            | ❌ NVIDIA 未覆盖 | Flare（眩光/杂散光）属于光学性能评估，NVIDIA EOL 文档未提及，本软件需独立实现。                                                              |
| 4. 畸变                             | —                                                            | ❌ NVIDIA 未覆盖 | 几何畸变（Distortion）不属于 NVIDIA EOL 标准测试项，本软件需独立标定。                                                                |
| 5. TV Distortion                  | —                                                            | ❌ NVIDIA 未覆盖 | 与畸变类似，TV Distortion 为特定光学评估指标，NVIDIA 文档未涉及。                                                                   |
| 6. FOV                            | —                                                            | ❌ NVIDIA 未覆盖 | 视场角（Field of View）不在 NVIDIA EOL 测试范围内，需独立测量。                                                                  |
| 7. Color 比例                       | **Brightfield → Color Uniformity**                           | ⚠️ 部分对齐      | NVIDIA 的 Color Uniformity 通过 Gr/R 和 Gr/B 比值的最大最小偏差评估；本软件的 **Color 比例** 若指 Bayer 通道比例或白平衡增益，则目标相近，但实现方式可能不同。   |
| 8. HDR                            | —                                                            | ❌ NVIDIA 未覆盖 | NVIDIA EOL 明确要求 **禁用 HDR/sequential HDR**，仅用单曝光测试；本软件的 HDR 评估是独立的扩展能力。                                        |
| 9. chromatic aberration           | —                                                            | ❌ NVIDIA 未覆盖 | 色差（CA）不在 NVIDIA EOL 标准项中，属于本软件额外的光学质量评估。                                                                      |
| —                                 | **Darkfield → Black Level**                                  | ❌ 本软件未规划     | 暗场黑电平标定，NVIDIA 要求每个通道分别计算并报告。                                                                                 |
| —                                 | **Darkfield → Defective Pixels / Clusters / Rows / Columns** | ❌ 本软件未规划     | 传感器坏点、坏点簇、坏行、坏列检测，属于 sensor-level EOL 必检项。                                                                    |
| —                                 | **Darkfield → Fixed Pattern Noise (FPN)**                    | ❌ 本软件未规划     | 固定模式噪声（Row / Column / Frame），暗场条件下评估。                                                                         |
| —                                 | **Darkfield → Temporal Noise**                               | ❌ 本软件未规划     | 时域噪声（Row / Column / Full），需多帧叠加分析。                                                                            |
| —                                 | **Darkfield → DSNU**                                         | ❌ 本软件未规划     | 暗信号非均匀性（Dark Signal Non-Uniformity），sensor 基础性能指标。                                                            |
| —                                 | **Brightfield → Center of Illumination**                     | ❌ 本软件未规划     | 光照中心偏移，用于评估镜头光轴与 sensor 对齐度。                                                                                  |
| —                                 | **Brightfield → PRNU**                                       | ❌ 本软件未规划     | 光响应非均匀性（Photo Response Non-Uniformity），亮场 sensor 均匀性核心指标。                                                     |
| —                                 | **Brightfield → Contamination**                              | ❌ 本软件未规划     | 异物/污染检测（Particles & Blemishes），通过中值滤波+阈值算法识别。                                                                 |
| —                                 | **SFR → SFR Uniformity (Lens Tilt)**                         | ❌ 本软件未规划     | 通过四角 SFR 差异评估镜头倾斜（Lens Tilt）。                                                                                 |
| —                                 | **SFR → SFR Falloff**                                        | ❌ 本软件未规划     | 中心 SFR 与边缘 SFR 的衰减量，量化像质从中心到边缘的下降。                                                                            |

### 三、总结

* **本软件强项**：覆盖光学镜头评估的核心指标（MTF、Lens Shading、畸变、FOV、Flare、色差、HDR），这些是面向 **镜头光学性能** 的全面评估，超出了 NVIDIA EOL 的 sensor + 基础光学验证范围。

* **NVIDIA EOL 强项**：覆盖了大量 **sensor-level** 和 **产线标定级** 测试项，包括暗场噪声（DSNU、Temporal Noise、FPN）、坏点/坏行/坏列、PRNU、Contamination、光照中心偏移、SFR Falloff/Tilt 等。这些是相机模组出厂（EOL）必检项，但本软件当前规划 **未涉及**。

* **建议**：若本软件未来需兼容 NVIDIA 模组 EOL 验证场景，建议优先补充 **SFR Falloff、Lens Tilt、PRNU、Darkfield 噪声系、Defective Pixel/Row/Column、Contamination** 等测试项。

***

# LeopardIQ IQ 测试软件计划书

> 版本：v1.0 · 2026-08-06
> 范围：首版聚焦 Phase 2 已完成的五大算法模块（MTF/SFR、Lens Shading、Color 比例、Flare、FOV）
> 参考风格：Imatest（模块化测试项 + 交互式 ROI + 结果图表 + 判定报告）

## 一、背景与目标

### 1.1 背景

* Phase 2 已完成 LeopardIQ 算法库提取，五大模块均提供 `analyze_*` 统一接口（`analyze_mtf` 系、`analyze_lens_shading` / `analyze_relative_illumination` / `analyze_multi_light`、`analyze_color_uniformity`、`analyze_flare`、`analyze_fov`），并支持 criteria 判定（PASS/FAIL）。

* 目前算法只能通过脚本调用，缺少面向镜头评估工程师的图形化工具。

### 1.2 目标

开发一款桌面端 IQ 测试软件（Imatest 风格），用于评估新镜头：

1. 加载 RAW / 图像文件，交互式完成各测试项的配置与执行；
2. 可视化展示结果（MTF 曲线、Shading 分布图、Flare 叠加图、FOV 参数等）；
3. 基于 criteria 自动判定 PASS/FAIL；
4. 导出测试报告（首版 PDF/CSV，HTML 可选）；
5. 架构上预留 Phase 3 扩展位（畸变、TV Distortion、色差、HDR 等）。

### 1.3 非目标（首版不做）

* 实时相机采集（首版仅离线文件分析，采集接入列入后续迭代）；

* sensor-level 暗场测试项（Black Level、坏点、DSNU 等，见上文 NVIDIA 对比）；

* 多工位产线部署 / 数据库管理。

## 二、功能范围（首版 = Phase 2 五模块）

| 模块               | 测试项                                   | 算法接口                                                                                                   | 主要交互                                           | 结果输出                          |
| ---------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------- | ----------------------------- |
| **MTF/SFR**      | 斜边 SFR、MTF50/MTF10、SFR 分布（中心+四角）、峰值对焦 | `compute_roi_sfr` / `compute_mtf_metrics` / `analyze_peak_focus` / `evaluate_mtf_values`               | ROI 框选斜边；图表类型选择（Square/Cross）；SFRMAT5 C++ 加速开关 | MTF 曲线图、MTF50 数值表、criteria 判定 |
| **Lens Shading** | 相对照度（RI）、亮度均匀性、四象限 RI、LSC 校正表、多光源对比   | `analyze_relative_illumination` / `analyze_lens_shading` / `analyze_multi_light`                       | 光源类型选择（D65/TL84/A 等）；亮度通道选择                    | RI 热力图、四象限数值表、LSC 表导出         |
| **Color 比例**     | Bayer 四通道比例、白平衡增益、Color Shading       | `analyze_color_uniformity`（内部 `compute_channel_ratios` / `compute_wb_gains` / `compute_color_shading`） | CFA pattern 选择（RGGB/BGGR/GRBG/GBRG）            | 通道比例表、G/R、G/B 分布图、判定结果        |
| **Flare**        | Type A / B / C 眩光                     | `analyze_flare`（内部 `FlareAnalyzer.analyze_type_a/b/c`）                                                 | 测试类型选择；双图加载（Type A/B）；debug 叠加图开关              | Flare 百分比、debug 叠加图、判定结果      |
| **FOV**          | 几何法 / 棋盘格法 FOV、Imatest JSON 导入        | `analyze_fov`（内部 `compute_fov_from_geometry` / `compute_fov_from_chessboard` / `parse_imatest_fov`）    | 棋盘格参数（格数、格尺寸 mm）；或拍摄距离参数                       | HFOV/VFOV/DFOV、角点检测预览图、判定结果   |

## 三、技术选型

| 项      | 选择                                  | 理由                                                                    |
| ------ | ----------------------------------- | --------------------------------------------------------------------- |
| 语言     | Python 3.12（conda 环境 `LpIQtest312`） | 与 leopardiq 库、测试环境一致；pyd 依赖 numpy<2 已固化                               |
| GUI 框架 | **PySide6（Qt）**                     | Imatest 类桌面软件的事实标准；与团队已有 Qt（msspDemo C++）经验衔接；QGraphicsView 适合交互式 ROI |
| 图表     | pyqtgraph（主）+ matplotlib（报告渲染）      | pyqtgraph 实时交互性能好；matplotlib 复用现有 debug 绘图风格用于导出                      |
| 图像处理   | OpenCV + numpy（沿用算法库依赖）             | 无新增重型依赖                                                               |
| 报告导出   | reportlab（PDF）+ pandas（CSV）         | 托管 Python 已内置                                                         |
| 打包     | PyInstaller / briefcase（后续）         | 首版以源码运行为主                                                             |

## 四、架构设计

### 4.1 分层

```
┌─────────────────────────────────────────────┐
│ UI 层（PySide6）                             │
│  main_window（Workflow 向导式主窗口）/       │
│  analysis_dialogs / figure_windows          │
│  /roi_editor /criteria_editor               │
├─────────────────────────────────────────────┤
│ 应用层（iqtest/）                             │
│  session（项目管理）/ runner（分析调度, QThread）│
│  / report（报告生成）/ config（criteria 持久化）│
├─────────────────────────────────────────────┤
│ 算法层（leopardiq/，已完成，不改动）             │
│  mtf / shading / flare / fov / utils        │
└─────────────────────────────────────────────┘
```

原则：

* **算法层零改动**：UI 只调用 `analyze_*(images, config) -> dict` 统一接口，返回 dict 直接驱动图表与表格；

* **分析异步执行**：`QThread` worker 跑算法，避免阻塞 UI；算法本身（含 pyd）无需改造；

* **config 驱动**：每个模块的参数（CFA、criteria 阈值、图表类型等）以 dict/JSON 描述，UI 自动生成表单，便于 Phase 3 新模块挂接。

### 4.2 目录规划（新增 `iqtest/`，与 `leopardiq/` 平级）

```
iqtest/
  main.py                 # 入口
  main_window.py          # 主窗口：左 Workflow 步骤栏 + 右 Source images 工作区
  session.py              # 测试会话：图像集、各模块结果、状态
  runner.py               # QThread 分析 worker
  panels/
    mtf_panel.py shading_panel.py color_panel.py
    flare_panel.py fov_panel.py   # 各分析项配置对话框（② Select Analysis 时弹出）
  figures/                # 结果 Figure 窗口（Imatest 风格独立弹窗，CLOSE FIGURES 统一管理）
    base_figure.py mtf_figure.py shading_figure.py flare_figure.py fov_figure.py
  widgets/
    image_view.py         # QGraphicsView：缩放、平移、ROI 框选
    roi_editor.py         # 斜边/区域 ROI 交互
    result_table.py       # 数值结果 + PASS/FAIL 着色
    curve_chart.py        # MTF 曲线（pyqtgraph）
    heatmap_view.py       # Shading / Color 分布热力图
  report/
    pdf_report.py csv_export.py
  config/
    default_criteria.json # 默认判定阈值
```

### 4.3 主界面布局（Workflow 向导式，参考 `assets/简化版图像分析软件 GUI 界面.jpeg`）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 📷 LeopardIQTS — 图像质量分析                                          _ □ ✕ │
├──────────────────────────────────────────────────────────────────────────────┤
│ File   JSON  Help                                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ ◆ Leopard │ 📈Analyze  ⚙Settings │ 🛠Utilities                               │
├─────────────────┬────────────────────────────────────────────────────────────┤
│ Workflow        │ Source images                                              │
│                 │ ┌──────────────┐                                           │
│ ① Select Images │ │ 🖼 IMAGES    │                                           │
│   No images     │ └──────────────┘                                           │
│   selected      │ ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐ │
│ │               │                                                             │
│ ② Select        │                                                             │
│   Analysis      │                                                             │
│                 │                                                             │
│ ┌─────────┐     │                                                             │
│ │  NEXT   │     │                                                             │
│ └─────────┘     │                                                             │
│ ┌───────────┐   │                  Drop image files here                      │
│ │ ANALYZE   │   │                                                             │
│ └───────────┘   │                        or                                   │
│                 │                                                             │
│ ┌─────────────┐ │   ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ │
│ │↻ START NEW  │ │   │🖼 SELECT IMAGES│ │☰ SELECT FOLDERS│ │▸ SELECT CAMERA │ │
│ │  ANALYSIS   │ │   └────────────────┘ └────────────────┘ └────────────────┘ │
│ └─────────────┘ │                                                             │
│ ┌─────────────┐ │    Use selected images ●────○ Acquire from device           │
│ │⊞ CLOSE      │ │                                                             │
│ │  FIGURES    │ │                                                             │
│ └─────────────┘ │                                                             │
│                 │                                                             │
│                 │                                                             │
│                 │                                                             │
│                 │                                                             │
│                 │ └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘ │
└─────────────────┴────────────────────────────────────────────────────────────┘
```

**交互流程**：

1. **① Select Images**：拖拽图像到虚线区，或经 SELECT IMAGES / SELECT FOLDERS / SELECT CAMERA 加载；底部 `Use selected images ◐ Acquire from device` 切换离线文件 / 相机采集（采集为后续迭代）；
2. **② Select Analysis**（NEXT 或点击步骤标题进入）：右侧切换为 Analysis options 页，**单选** MTF/SFR、Lens Shading、Color、Flare、FOV 中的一项（各测试项拍摄环境 / 靶标不同，一批图像仅对应一个测试），并配置其参数与 criteria（panel）；步骤栏下方实时显示当前所选测试项；
3. **ANALYZE**：后台 QThread 运行所选分析，结果以 **独立 Figure 窗口** 弹出（Imatest 风格，可并排对比）；**CLOSE FIGURES** 一键关闭全部结果窗；
4. **START NEW ANALYSIS**：清空会话，开始新一轮测试。

**菜单/工具栏分工**：

* **File**：打开/保存会话、导出报告（PDF/CSV）、退出；

* **JSON**：criteria 判定阈值与各模块默认参数的读取/保存（JSON 持久化）；

* **Analyze**：直接进入分析选择与运行（与 Workflow ② 联动）；

* **Settings**：全局设置（RAW 解析参数、CFA 默认 pattern、加速开关）；

* **Utilities**：报告导出、批量分析、Imatest JSON 导入（FOV）等辅助工具；

* **Help**：关于、用户手册。

## 五、里程碑与排期

> 单人开发估算，总计约 **5\~6 周**。

| 里程碑          | 内容                                                                                               | 交付物        | 工期   |
| ------------ | ------------------------------------------------------------------------------------------------ | ---------- | ---- |
| **M1 骨架**    | PySide6 主窗口（Workflow 步骤栏 + Source images 工作区）、图像加载（拖拽/文件/文件夹，RAW/PNG）、菜单与工具栏框架                   | 可打开图像的空壳软件 | 3 天  |
| **M2 交互基础**  | ② Select Analysis 分析选择对话框、config 表单自动生成、criteria 编辑与 JSON 持久化、分析 worker（QThread）、Figure 窗口框架 | 交互框架就绪     | 4 天  |
| **M3 模块接入**  | 五个 panel 逐一接入 `analyze_*` 接口 + 结果可视化（MTF 曲线、RI 热力图、通道比例表、Flare 叠加图、FOV 角点预览）                     | 五模块全流程可用   | 10 天 |
| **M4 报告与判定** | 汇总判定页（各模块 PASS/FAIL 总览）、PDF/CSV 报告导出、会话保存/加载                                                     | 完整测试闭环     | 4 天  |
| **M5 打磨**    | 异常处理（缺图/参数非法/算法报错）、快捷键、界面美化、用户手册、回归测试                                                            | 首版发布候选     | 4 天  |

### 每模块接入的标准步骤（M3 内复用）

1. 定义模块 config schema（参数 + 默认值 + criteria）；
2. 实现 panel：参数表单 + 图像/ROI 准备 + 调 `analyze_*`；
3. 结果 dict → 表格/图表控件映射；
4. 用 Phase 2 测试用的合成图/实拍摄图做端到端验证，与脚本结果对拍。

## 六、测试与验收

* **单元层**：复用 Phase 2 测试（38+25+15+18 项），算法层改动为零故无需新增；UI 层对 session/runner/report 做 pytest（pytest-qt 可选）。

* **集成层**：每个模块一条端到端用例（加载 → 配置 → 运行 → 判定 → 导出），结果与脚本对拍一致。

* **验收标准**：

  1. 五大模块均可独立完成「加载图像 → 出结果 → PASS/FAIL」闭环；
  2. 同一图像的 GUI 结果与 `leopardiq` 脚本结果一致（数值容差 1e-6）；
  3. 可导出包含全部模块结果的 PDF 报告。

## 七、风险与对策

| 风险                               | 影响       | 对策                                                         |
| -------------------------------- | -------- | ---------------------------------------------------------- |
| RAW 格式多样（不同 sensor/位宽/CFA）       | 图像加载兼容性  | 首版支持已在算法库验证的格式（raw 二进制 + 参数指定），其余走 OpenCV 常见格式；采集接入迭代时统一处理 |
| pyd（SFRMAT5）仅限 Windows + numpy<2 | 部署受限     | 保留纯 Python 回退路径；环境用 conda 固化                               |
| 交互式 ROI 工作量大                     | M2/M3 延期 | 首版 ROI 只做矩形+斜边两种；复杂交互（拖拽顶点）放迭代                             |
| Phase 3 模块接入导致架构返工               | 后期成本     | config 驱动 + 统一 `analyze_*` 接口已在 Phase 2 定型，新模块只需加 panel    |

## 八、后续迭代方向（衔接 Phase 3）

1. **Phase 3 模块挂接**：畸变 / TV Distortion（复用 FOV 棋盘格角点）、色差、HDR；
2. **实时采集**：接 Leopard Imaging 相机（mssp SDK），在线跑分析；
3. **NVIDIA EOL 对齐**：补 Darkfield 噪声系、坏点、PRNU、SFR Falloff/Tilt（见上文对比表）；
4. **批量模式**：多镜头批量回归 + 报告对比。

