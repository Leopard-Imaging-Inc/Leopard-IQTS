# LeopardIQ-IQ测试软件 — MTF/SFR 模块开发总结

> 对应规划：`doc/LeopardIQ-IQ测试软件规划.md` 里程碑 **M3（MTF/SFR 模块接入）**。
> 本文档汇总 MTF 功能迄今的全部开发内容，作为后续「MTF 参数设置」开发的基线。
> 更新日期：2026-08-10（新增频率单位 Secondary Readout 风格设置，见 §5.3；
> 新增 MTFnn / MTFnnP 读数类型，见 §5.4）。
> 更新日期：2026-08-11（新增 Gamma (input) 线性化参数，见 §9；新增附录
> §11「MTF 测试全流程操作步骤」，按代码实际交互梳理用户视角的完整操作链路）。
> 更新日期：2026-08-14（MTF 引擎前置预检防段错误、适配器引擎调用去重、
> 引擎输出 NaN 曲线清洗等健壮性优化，见 §12）。
> 更新日期：2026-08-17（新增 MTF 结果 CSV 导出——模组性能比较的前置功能，
> 见 §15；适配器 details 补充 image_sizes）。

---

## 1. 功能概览

MTF/SFR 模块已实现从图像载入到结果判定的完整闭环：

```
Select Images → MTF 面板载入图像（支持 RAW）→ 「框选…」弹窗画 ROI + 精调
→ ANALYZE → compute_roi_sfr / compute_mtf_array 算法适配
→ MTF 曲线 Figure（pyqtgraph）+ 逐 ROI PASS/FAIL 判定
```

- 斜边 SFR 算法：每个 ROI 须包含一条黑白斜边；
- 指标：MTF @ 评估频率（参与判定）、MTF50（参与判定）、
  两个可配置 Secondary Readout（MTFnn/MTFnnP，INFO）；
- 判定：MTF50 下限 + MTF@评估频率 SFR 下限 → PASS / FAIL；
- 结果展示：MTF 曲线图 + 逐通道指标表 + 总判定横幅。

## 2. 文件清单

| 文件 | 职责 |
|------|------|
| `iqtest/panels/mtf_panel.py` | MTF 面板：图像载入、ROI 工具行（查看/框选互斥）、频率单位联动换算、参数与 criteria 表单、config 读写 |
| `iqtest/widgets/image_view.py` | 主视图 `RoiImageView`：纯查看模式（平移/缩放/选中/双击精调/删除），不提供框选 |
| `iqtest/widgets/roi_dialog.py` | `RoiFineTuneDialog`：框选 + 精调合一弹窗（Imatest 风格） |
| `iqtest/analysis/mtf_adapter.py` | 算法适配器 `analyze_mtf`：图像加载（含 RAW）、频率单位 → cy/px 换算、逐 ROI 计算、判定、结果组装（details 含 `image_sizes`：图像名 → [W, H]，§15） |
| `iqtest/analysis/mtf_export.py` | MTF 结果 CSV 导出（模组比较前置）：`result_to_csv` / `write_result_csv` / `compute_mtfa`（§15） |
| `iqtest/figures/mtf_figure.py` | 结果 Figure `MtfResultView`：MTF 曲线（按所选单位显示）+ 指标表 + 判定横幅 + 「导出结果 CSV…」按钮（§15） |
| `leopardiq/mtf/units.py` | 空间频率单位换算：Cycles/pixel、Cycles/mm、LP/mm、L/mm、LP/PH、LW/PH（§5.3） |
| `tests/test_m3_1.py` | M3 单元测试（7 组 37 断言，全部通过） |
| `tests/test_m3_2.py` | M3.2 频率单位测试（4 组 38 断言，全部通过） |
| `tests/test_m3_3.py` | M3.3 Secondary Readout 读数类型测试（4 组 33 断言，全部通过） |
| `tests/test_m3_4.py` | M3.4 Gamma (input) 线性化参数测试（4 组 26 断言，全部通过） |
| `tests/test_m4_1.py` | M4.1 MTF 结果 CSV 导出测试（6 组 40 断言，全部通过，§15） |
| `scripts/screenshot_m3.py` | M3 冒烟脚本：GUI 全链路 + 截图 |
| `scripts/check_view_interactions.py` | 主视图交互事件级验证（选中/双击/删除） |
| `tests/_m3_smoke/` | 冒烟截图与运行日志输出目录 |

外部依赖：`leopardiq`（算法包：`compute_roi_sfr`、`compute_mtf_array`、`compute_mtf_metrics`、`read_raw_image`、`evaluate_pass_fail`）、`pyqtgraph==0.14.0`、OpenCV、PySide6。

## 3. 图像载入与 RAW 支持

入口：`mtf_adapter.load_analysis_image(path, params)` → `(H, W, 1) float32`。

- **常见格式**（png/jpg/bmp/tif/webp）：OpenCV 直接解码转灰度。
- **`.raw` 二进制**（流程参考 `F:\project\python\Cal_MTF\scripts\mtf_single.py`）：
  1. uint16 单通道读取（`read_raw_image`，10/12/14-bit 左移到 16bit）；
  2. Bayer 时按 CFA pattern 用 `cv2.demosaicing` 去马赛克 → 转灰度，**保持全分辨率**。
  （2026-08-14 起：Read Raw 全局设置不再暴露字节序/黑电平——固定
  little-endian、不扣黑电平，MTF 流程不使用这两项；底层 `RawReadConfig`
  仍保留这两个参数供其他模块使用。）
- **分辨率自动识别**：参数 `raw_width/raw_height` 与文件大小不符时，按常见 sensor
  分辨率表（`COMMON_RESOLUTIONS`，含 1920×1200 等 20 种）自动匹配；识别失败给出明确报错。
- **CFA → OpenCV 映射（实测校准，勿改）**：OpenCV 命名与习惯命名错位——
  RGGB→`COLOR_BayerBG2BGR`、BGGR→`COLOR_BayerRG2BGR`、
  GRBG→`COLOR_BayerGB2BGR`、GBRG→`COLOR_BayerGR2BGR`。
- 已验证的真实数据：`assets/data/MTF/camera_0/1/2-0.6/SN_2-0.6_D_07_28_2026_T_16_37_32.raw`
  （1920×1200，产线 CSV 含 10 个 ROI 框，见测试 [7/7]）。

## 4. ROI 交互设计（Imatest 风格）

### 4.1 主视图：固定「查看」模式（防误触）

工具行：**[查看] [框选…] [适应窗口] [清空 ROI]**。

- 「查看」「框选…」为 `QButtonGroup` **互斥单选按钮**，激活项青色高亮
  （`style.py` 的 `QPushButton:checked` 规则），弹窗关闭后自动恢复「查看」选中；
- 查看模式功能：拖拽平移、滚轮缩放、**单击选中 ROI**（橙色高亮）、
  **双击 ROI 弹出框选/精调窗口**、**右键菜单或 Delete 键删除单个 ROI**、清空全部；
- 主视图不能画框，彻底避免误触。

### 4.2 「ROI 框选 / 精调」弹窗（`RoiFineTuneDialog`）

框选与精调合一，两个入口共用同一窗口：

- **框选入口**（`draw_new=True`，点「框选…」）：初始显示全图 + 橙色提示 +
  十字光标，拖拽画虚线粗框；**画出前精调控件与「确定」全部禁用**；
  画出后自动放大到该 ROI 进入精调态；取消不留痕。
- **精调入口**（双击 ROI）：直接定位到被双击的 ROI。

精调能力（对应 Imatest ROI fine adjustment）：

- 整体移动：↑↓←→ 方向键按钮；
- 单边缘调整：T^/Tv（Top 上/下移）、B^/Bv、L</L>、R</R> 环绕布局，
  **步长单选按钮居中：1 / 5 / 15 pixel**（默认 1px）；
- L/R/T/B 数值框直接输入像素坐标（自图像左上角，回车生效）；
- 视图：滚轮缩放、拖拽平移、「显示全图 / 适应 ROI」切换；
- 多 ROI 时「上一个 / 下一个」切换编辑；
- 按钮最小 46px + 横向自适应、控制面板宽 250px（修复文字截断）。

## 5. 算法适配（`analyze_mtf`）

签名：`analyze_mtf(images, config) -> dict`（runner 约定），返回对齐 `SFRAnalyzer`：
`{"metrics", "pass", "details", "visualization"}`。

流程：加载并缓存图像 → 逐 ROI 裁剪 patch（`_clip_rect` 越界裁剪、最小 8px）
→ `compute_roi_sfr`（SFR@评估频率，与 Phase 2 脚本同口径可互相对拍）
→ `compute_mtf_array` + `compute_mtf_metrics`（MTF 曲线 + MTF50/MTF30）
→ `evaluate_pass_fail` 下限判定 → 汇总。

### 5.1 当前参数（params）

| key | 默认 | 说明 |
|-----|------|------|
| `cfa` | `Y` | CFA pattern：Y / RGGB / BGGR / GRBG / GBRG |
| `pixel_size_um` | 2.0 | 像元尺寸（µm/px），Cycles/mm、LP/mm、L/mm 换算所需 |
| `picture_height` | 1080 | 像高（px），LP/PH、LW/PH 换算所需；载入图像后自动填入图像高度 |
| `freq_unit` | `Cycles/pixel` | 频率单位：Cycles/pixel、Cycles/mm、LP/mm、L/mm、LP/PH、LW/PH（§5.3） |
| `freq1` | 0.125 | 评估频率（MTF @ nn），按所选单位输入，SFR 值参与 criteria 判定 |
| `mtfnn1_type` / `mtfnn1_value` | `MTFnn` / 30 | Secondary Readout 槽位 1（§5.4） |
| `mtfnn2_type` / `mtfnn2_value` | `MTFnnP` / 50 | Secondary Readout 槽位 2（§5.4） |
| `raw_width` | 1920 | RAW 宽度（不符时自动识别）；向后兼容旧配置，新配置由 Read Raw 全局设置承担 |
| `raw_height` | 1080 | RAW 高度；同上 |
| `rois` | — | 由 ROI 框选注入：`[{"image": 文件名, "rect": [x,y,w,h]}]` |

校验：换算为 cy/px 后需满足 `0 < freq1 ≤ 1.0`；未框选 ROI 时报明确错误。

### 5.2 当前判定（criteria）

| key | 默认 | 说明 |
|-----|------|------|
| `mtf50_min` | 0.10 | MTF50 下限，按所选频率单位输入（默认 0.10 cy/px） |
| `sfr_main_min` | 0.20 | MTF@评估频率（freq1）SFR 下限（0~1，无单位） |

逐 ROI 判定 = 该 ROI 全部判据的与（无效 ROI 记 FAIL）；
总判定 = 全部 ROI 有效 且 无 FAIL。

### 5.3 频率单位（仿 Imatest Secondary Readout，2026-08-10 新增）

算法层统一使用规范单位 **cy/px**；界面输入与结果展示支持 6 种单位
（`leopardiq/mtf/units.py`）：

| 单位 | 与 cy/px 的关系 | 需要的附加参数 |
|------|----------------|----------------|
| Cycles/pixel | 基准 | — |
| Cycles/mm | × 1000 / pixel_size_um | 像元尺寸 |
| LP/mm | 同 Cycles/mm | 像元尺寸 |
| L/mm | 2 × LP/mm | 像元尺寸 |
| LP/PH | × picture_height | 像高 |
| LW/PH | 2 × LP/PH | 像高 |

- **面板联动**：切换 `freq_unit` 时，freq1 / mtf50_min 的显示值实时
  换算（先读后换算再扩量程，避免 SpinBox 取整/截断），行标签同步显示当前单位；
  SpinBox 量程/精度按单位切换（cy/px：0~1 三位小数；其余：大量程两位小数）。
- **config 存储**：数值按所选单位原样存储 + `freq_unit` 键；旧配置无
  `freq_unit` 时按 Cycles/pixel 解释，完全向后兼容。
- **适配器**：`analyze_mtf` 将 freq1/mtf50_min 换算为 cy/px 后计算与判定；
  缺像元尺寸/像高或换算后频率越界时给出明确报错；
  `details` 携带 `freq_unit` / `unit_scale` 供 Figure 显示。
- **Figure**：曲线频率轴、Nyquist/主频参考线、MTF50 落点、指标表
  MTF50/MTF30 列均按所选单位显示（SFR@ 列为 0~1 无单位量，不换算）。

### 5.4 Secondary Readout 读数类型（2026-08-10 新增）

对应 Imatest Secondary Readout 的 MTFnn / MTFnnP / MTF @ nn 三种读数：

| 读数类型 | 含义 | 本软件对应 |
|----------|------|-----------|
| MTF @ nn | 指定空间频率处的 SFR 值 | 评估频率 `freq1`，指标键 `ROIn_mtf@{freq}`，参与判定（`sfr_main_min`） |
| MTFnn | MTF 降至低频值 nn% 处的空间频率 | 槽位 1/2 `mtfnn{1,2}_type=MTFnn`（INFO 展示） |
| MTFnnP | MTF 降至峰值 nn% 处的空间频率（适合强锐化图像） | 槽位 1/2 `mtfnn{1,2}_type=MTFnnP`（INFO 展示） |

- 2 个可配置槽位（默认：槽位 1 = MTF30、槽位 2 = MTF50P），
  每个槽位独立选择 MTFnn / MTFnnP 与百分比 nn；
- `compute_mtf_metrics` 泛化为 `mtfNN` / `mtfNNp` 任意百分比（正则解析，
  NN ∈ (0, 100)），旧名 `mtf50`/`mtf30`/`mtf50p`/`mtf30p` 完全兼容；
- 与判定键 `mtf50` 重复或两槽位重复的读数自动去重；
- MTFnn(P) 为 INFO 指标，不参与 PASS/FAIL 判定；判定由
  `mtf50_min`（MTF50 下限）与 `sfr_main_min`（MTF@评估频率 SFR 下限）承担；
- Figure 指标表：MTF @ 列 + MTF50 列 + 各 readout 动态列
  （如 `MTF30 (cy/px)`、`MTF50P (LP/mm)`），频率类数值按 §5.3 单位换算；
- 注：2026-08-10 起删除 `freq2`（原「评估频率 2 / 主频」），
  判定改为 `freq1` 一处；旧配置中的 `freq2` 键会被忽略。

## 6. 结果 Figure（`MtfResultView`）

- 顶部：PASS（绿）/ FAIL（红）横幅 + 评估频率与 criteria 摘要；
- 左侧 pyqtgraph 曲线图：逐 (ROI, 通道) MTF 曲线（ROI 轮换配色、通道轮换线型），
  Nyquist 0.5 与主频参考线；
- 交互增强：**ROI 选中高亮**（点击右侧指标表行或图中曲线，选中曲线加粗、其余淡化，
  再次点击或点击空白处取消）、**MTF50 / MTF30 标注开关**（可勾选按钮，默认关闭，勾选后
  标出落点并画垂线连 x 轴 + 水平线连 y 轴；选中某 ROI 时仅标注该 ROI 的落点）、
  **复位视图**（一键还原被拖动/缩放后的曲线图坐标范围）；
- MTF50 / MTF30 开关**同时控制右侧指标表对应列（`MTF50` / `MTF30`）显隐**；
  当 Readout1 百分比 nn = 50 / 30 时，该列即 Readout1 判定列，**始终显示**（开关不隐藏）；
- 右侧指标表：ROI / 通道 / MTF @ 评估频率 / MTF50 / 各 Secondary Readout 列 / 判定；
- 通过 `FigureManager.register_view("mtf", MtfResultView)` 嵌入 Figure 窗口，
  CLOSE FIGURES 可统一关闭。

## 7. config 持久化

- `config()`：ROI 列表注入 `params["rois"]`（含图像名，图像坐标 int）；
- `set_config()`：恢复表单 + 暂存 ROI（`_pending_rois`），载入同名图像后自动回填；
- 已载入图像被移出会话时自动清空视图与 ROI。

## 8. 测试与验证

| 项 | 结果 |
|----|------|
| `tests/test_m3_1.py` | **37 断言全部通过**：mono 端到端、Bayer RAW 端到端、criteria/错误路径、schema/JSON、RAW 加载（含自动识别分辨率、4 种 CFA 通道正确性）、真实 RAW（9/10 ROI 有效、MTF50∈(0.05,0.6)、中心 ROI 不劣于四角） |
| `tests/test_m3_2.py` | **38 断言全部通过**：6 单位换算与往返、缺参报错、LP/mm 与 LW/PH 配置端到端结果与 cy/px 完全一致、面板单位切换实时换算与 config 往返 |
| `tests/test_m3_3.py` | **33 断言全部通过**：mtfNN/mtfNNp 泛化计算（含过锐化峰值归一化）、指标名校验、适配器双槽位 MTFnn/MTFnnP 端到端、重复读数去重、nn=50 去重、面板 schema 往返 |
| `tests/test_m3_4.py` | **26 断言全部通过**：linearize_gamma 单元行为、Gamma 编码往返一致性（编码图 γ=0.5 线性化后 ≈ 线性参考）、适配器端到端（默认 γ=1.0 兼容、编码图 γ=0.5 还原、γ 记录进 details/curves/rois）、旧版 linearization/chart_contrast 键兼容忽略、非法配置报错、面板默认值与 config 往返 |
| `scripts/screenshot_m3.py` | 冒烟 EXIT=0：合成图全链路 → ANALYZE → Figure → 真实 RAW（1920×1200 自动识别）→ 精调弹窗移动/边缘/步长/回写 → draw_new 画框回写；互斥单选断言 |
| `scripts/check_view_interactions.py` | 事件级：单击选中 / 双击精调信号 / Delete 删除 全部 OK |
| M1/M2 冒烟 | 无回归 |

运行方式（Git Bash，项目根，conda 环境 `LpIQtest312`）：

```bash
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m3_1.py
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m3_2.py
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m3_3.py
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m3_4.py
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u scripts/screenshot_m3.py
```

## 9. 后续待议（参数设置开发锚点）

以下 MTF 参数已明确**留待后续讨论**，当前均未实现，勿默认已有：

- **测哪些 MTF 值**：当前为 MTF50（判定）+ 1 个评估频率点 MTF@（判定）+
  2 个可配置 MTFnn/MTFnnP 槽位（INFO）（§5.4，2026-08-10 已实现）；仍可讨论：
  更多 Secondary Readout 槽位（Imatest 有 3 个）、MTF Area 面积指标、
  MTFnn 纳入 criteria 判定等；
- **Gamma 设置**（2026-08-11 已实现）：仿 Imatest「Input gamma value」——
  编码 Gamma 倒数线性化 pixel^(1/γ)，默认 γ=1.0 即不线性化、适用于线性
  RAW；BMP/JPEG 等 sRGB 编码图像设 0.45~0.5；超出 0.3~0.8 且 ≠1.0 时给出
  异常警告。项目仅用 RAW / BMP（编码已知），故不含 Imatest 的
  「Gamma calculated from chart contrast」估算方式。
  算法层 `compute_mtf_array` / `compute_roi_sfr` / `extract_edge_roi_sfr` /
  `SFRAnalyzer` 均已透传 `gamma`；适配器将实际使用的 Gamma 逐 ROI 记录进
  details/curves；仍可讨论：sRGB 精确分段曲线（IEC 61966-2-1）替代纯幂律、
  按图像格式自动建议 Gamma（.raw→1.0，.bmp/.jpg→0.5）等；
- 其他可能项：ROI 最小尺寸策略、通道选择（R/G/B 分离计算）、归一化方式、
  结果导出（CSV/报告）。

## 10. 已知限制（非 bug）

- 冒烟截图中文显示为方框：offscreen 环境无 CJK 字体，实际运行正常；
- RAW 预览为去马赛克后的灰度图（棋盘格纹理来自真实 sensor 数据本身）；
- `.raw` 按 uint16 小端读取，暂不支持 packed 10/12-bit RAW；
- 右键删除菜单为模态 `QMenu`，自动化测试中不可直接断言（已用事件级测试覆盖其余交互）。

---

## 11. MTF 测试全流程操作步骤（用户视角）

以下按代码实际交互（`main_window.py` / `mtf_panel.py` / `read_raw_dialog.py`
/ `mtf_adapter.py`）梳理一次完整 MTF 测试的操作链路，可作为使用手册与
回归验证清单。

```
启动 LeopardIQTS
  →（RAW 图像时）步骤 0：Utilities → Generalized Read Raw 配置读取参数
  → 步骤 1：① Select Images 加载图像
  → 步骤 2：② Select Analysis 勾选 MTF / SFR
  → 步骤 3：MTF 面板「载入图像」
  → 步骤 4：「框选…」画斜边 ROI（可双击精调 / 右键删除）
  → 步骤 5：设置参数（频率单位/评估频率/Readout/Gamma）与判定 criteria
  → 步骤 6：ANALYZE → 后台 QThread 运行算法
  → 步骤 7：MTF 结果 Figure（曲线 + 指标表 + PASS/FAIL 横幅）
  →（可选）步骤 8：JSON 菜单保存/读取 criteria 配置，或 START NEW ANALYSIS
```

### 步骤 0（仅 .raw）：Utilities → Generalized Read Raw 配置 RAW 读取

入口：顶部品牌栏 **🛠 Utilities → Generalized Read Raw…**（`ReadRawDialog`）。

1. 填写读取参数：宽度 / 高度（**填 0 时按文件大小自动识别常见分辨率**）、
   位深、CFA pattern（Y / RGGB / BGGR / GRBG / GBRG）、是否去马赛克、
   灰度转换方法；
   （2026-08-14 起移除字节序/黑电平参数：固定 little-endian、不扣黑电平，
   MTF 流程不使用这两项）
2. 点 **「读取测试…」** 选一个 .raw 试读并预览：Bayer 显示彩色去马赛克图
   （可直接核对 CFA pattern 是否选对），mono 显示灰度图；
   信息行显示识别出的分辨率与 min/max；
3. 点 **「保存」**：设置全局持久化，之后所有模块读取 .raw 均使用此配置
   （`iqtest/config/read_raw_settings.py`）。

> 常见格式（png/jpg/bmp/tif/webp）由 OpenCV 直接解码，跳过本步骤。

### 步骤 1：① Select Images 加载图像

1. 默认停在 **① Select Images**，右侧为 Source images 页；
2. 加载方式（三选一）：**拖拽图像文件**到右侧区域 / 点 **SELECT IMAGES**
   选文件 / 点 **SELECT FOLDERS** 整目录扫描；
3. 已加载图像显示为缩略图卡片网格，**右键卡片可移除**；
   左侧步骤 1 状态实时显示 `N image(s) selected`。

### 步骤 2：② Select Analysis 勾选 MTF / SFR

1. 点左侧 **NEXT**（或直接点步骤 ② 标题）切到 Analysis options 页；
2. 在左侧模块列表勾选 **MTF / SFR**（各模块互斥单选：一批图像只对应
   一个测试项）；右侧即显示 MTF 面板（参数 + criteria + ROI 工具）。

### 步骤 3：MTF 面板「载入图像」

1. 在「ROI 框选（斜边）」区的 **源图像** 下拉框中选择会话中的一张图像；
2. 点 **「载入图像」**：
   - .raw 按步骤 0 的全局 Read Raw 设置读取（Bayer 去马赛克
     → 灰度，保持全分辨率）；分辨率不符时自动识别，失败给出明确报错弹窗；
   - 载入成功后主视图显示图像并自动适应窗口；
   - **像高（picture_height）自动填入图像高度**（裁剪图应手动改为原始
     全幅像高，否则 LP/PH、LW/PH 换算不准）；
3. 若之前通过 criteria JSON 恢复过 ROI（`set_config`），载入同名图像后
   ROI 自动回填。

### 步骤 4：框选斜边 ROI（Imatest 风格）

主视图固定为「查看」模式，工具行：**[查看] [框选…] [适应窗口] [清空 ROI]**
（查看/框选为互斥单选，激活项高亮）。

- **画框**：点 **「框选…」** 弹出「ROI 框选/精调」窗口（`RoiFineTuneDialog`），
  初始显示全图 + 十字光标，**拖拽画出虚线粗框**（画出前精调控件与
  「确定」均禁用，取消不留痕）；画出后自动放大进入精调态；
- **精调**：方向键整体移动；T^/Tv、B^/Bv、L</L>、R</R> 单边缘调整，
  步长单选 **1 / 5 / 15 px**；L/R/T/B 数值框直接输入像素坐标（回车生效）；
  多 ROI 用「上一个 / 下一个」切换；确认后写回主视图；
- **查看模式下的 ROI 管理**：拖拽平移、滚轮缩放、**单击选中**（橙色高亮）、
  **双击 ROI 重新弹出精调窗口**、**右键菜单或 Delete 键删除单个 ROI**、
  「清空 ROI」清除全部；ROI 计数实时显示在工具行右侧；
- **要求**：每个 ROI 必须包含一条黑白斜边（推荐 4:1 对比度斜边，ROI 尺寸
  建议 40×40 px 以上，越界自动裁剪、最小 8px）。

### 步骤 5：设置参数与判定 criteria

**Parameters（表单，详见 §5.1）：**

| 操作 | 说明 |
|------|------|
| 选频率单位 | Cycles/pixel、Cycles/mm、LP/mm、L/mm、LP/PH、LW/PH；**切换单位时 freq1 / mtf50_min 数值自动换算**（Cycles/mm 等需像元尺寸，LP/PH 等需像高，缺参弹窗警告） |
| 评估频率 MTF @ | 读取该频率处的 SFR 值，**参与判定**（默认 0.125 cy/px = Nyquist/4） |
| Secondary Readout 1/2 | 各选 MTFnn / MTFnnP + 百分比 nn（默认 MTF30、MTF50P），**INFO 展示不参与判定** |
| Gamma (input) | 编码 Gamma 倒数线性化 pixel^(1/γ)：RAW 线性数据 = 1.0（默认）；BMP/JPEG 等 sRGB 编码图像 ≈ 0.45~0.5；超 0.3~0.8 且 ≠1.0 分析时给警告 |

**Criteria（判定，详见 §5.2）：** MTF50 下限（按所选频率单位输入，默认
0.10）+ MTF@评估频率 SFR 下限（0~1 无单位，默认 0.20）。

### 步骤 6：ANALYZE 执行分析

1. 点左侧 **ANALYZE** 按钮（未加载图像 / 未勾选分析项时状态栏提示并
   自动跳转到对应步骤）；
2. 分析在 **QThread 后台运行**，期间 ANALYZE 按钮禁用防重入；
3. 算法链路（`analyze_mtf`）：加载图像（缓存）→ 逐 ROI 裁剪 patch →
   `compute_roi_sfr`（SFR@评估频率）+ `compute_mtf_array` /
   `compute_mtf_metrics`（MTF 曲线、MTF50、各 Readout）→
   `evaluate_pass_fail` 下限判定；
4. **未框选 ROI 时报错**：「尚未框选 ROI：请在 ② Select Analysis →
   MTF / SFR 面板载入图像并框选至少一个斜边 ROI」；模块失败在结束后
   弹窗汇总，状态栏显示成功/失败数。

### 步骤 7：查看结果 Figure（`MtfResultView`）

分析完成自动弹出 MTF 结果窗口：

- **顶部横幅**：PASS（绿）/ FAIL（红）+ 评估频率与 criteria 摘要；
  判定规则 = 逐 ROI 全部判据取与（无效 ROI 记 FAIL），
  总判定 = 全部 ROI 有效且无 FAIL；
- **左侧曲线图**：逐 (ROI, 通道) MTF 曲线（ROI 轮换配色、通道轮换线型）、
  Nyquist 0.5 与评估频率参考线、MTF50 落点散点，频率轴按所选单位显示；
- **右侧指标表**：ROI / 通道 / MTF @ 评估频率 / MTF50 / 各 Secondary
  Readout 列 / 判定；
- **⊞ CLOSE FIGURES** 一键关闭全部结果窗口。

### 步骤 8（可选）：配置复用与新一轮测试

- **JSON 菜单**：「保存 criteria 配置 (JSON)…」将当前模块参数 + criteria +
  ROI 列表（随 `params["rois"]`）存为 JSON；「读取 criteria 配置 (JSON)…」
  恢复（ROI 在载入同名图像后自动回填）；「恢复默认 criteria」重置；
- **↻ START NEW ANALYSIS**：确认后清空图像、已选分析项并关闭全部 Figure，
  回到步骤 1 开始新一轮测试。

---

## 12. MTF 引擎健壮性与计算优化（2026-08-14 新增）

参考 `lf-1.6.5/mtf_test.py` 与《Raw数据处理流程.md》的引擎健壮性结论
（平坦图 → "s >= 0" 异常、水平/垂直边缘 → "empty matrix" 异常、
**纯噪声图直接段错误 0xC0000005 且 Python 无法捕获**），做以下优化：

| 改动 | 文件 | 说明 |
|------|------|------|
| 引擎前置预检 `validate_edge_patch` | `leopardiq/mtf/mtf_calculator.py` | 进入 C++ 引擎前拦截无效 ROI：形状/NaN/动态范围检查 + **结构张量相干性**（≥0.5，拦纯噪声防段错误）+ 边缘法向阶跃对比度（≥10% 动态范围，拦孤立亮线等伪边缘）。`compute_mtf_array` 内置调用，`compute_roi_sfr` / `SFRAnalyzer` / `peak_focus` / 适配器全部自动受保护 |
| 引擎输出 NaN 清洗 | `leopardiq/mtf/mtf_calculator.py` | 引擎对退化 ROI 可能返回**全 NaN 曲线**（不返回 None、不抛异常）；`compute_mtf_array` 统一剔除含 NaN 采样点，有效点 <2 视为失败；`interpolation_nyquist` / `interpolation_mtf` / `compute_mtf_metrics` 均有空曲线兜底（返回 NaN/0.0 而非崩溃） |
| 适配器引擎调用去重 | `iqtest/analysis/mtf_adapter.py` | 原每 (ROI, 通道) 调 2 次 C++ 引擎（`compute_roi_sfr` + `compute_mtf_array`）；改为单次调用得 MTF 曲线，SFR@评估频率由 `interpolation_nyquist` 插值——同引擎同插值函数，结果与 `compute_roi_sfr` 完全一致（对拍容差 1e-6），引擎调用次数减半。ROI < 20px 时增加尺寸偏小警告 |
| peak_focus 健壮性 | `leopardiq/mtf/peak_focus.py`、`leopardiq/mtf/centroid.py` | 引擎返回 None 或插值 NaN 时跳过该 patch（原为 TypeError 崩溃）；距离结果全 NaN 时抛明确 RuntimeError；质心检测无匹配连通域时抛明确错误（原 argmin 空序列崩溃） |
| 灰度系数标注修正 | `leopardiq/utils/image_preprocess.py` | `bayer_to_luminance` 的 0.2126/0.7152/0.0722 为 **BT.709** 系数（原 docstring 误标 BT.601） |

新增 `tests/test_m3_5.py`（5 组 23 断言）：预检单元测试、噪声 ROI 不崩溃、
适配器与 `compute_roi_sfr` 对拍一致、噪声 ROI 端到端 FAIL、peak_focus 防护。
回归：test_m3_1~m3_4（134 断言）、test_phase2_1/2/4/5（96 断言）、
screenshot_m3 冒烟（EXIT=0）全部通过。

## 13. 与 lf-1.6.5 mtf_test.py 的数值差异定位（2026-08-14 新增）

同一 RAW（`camera_0/1/3-0.55/SN_3-0.55_...raw`，1920×1200 10bit GRBG）
+ 同一 10 个 ROI，两项目 MTF@Nyquist25（0.125 cy/px）结果相差 ≤0.003。
对照实验（`reference/compare_lf165.py`，同一 C++ 引擎、4 种预处理变体）定位：

| 变体 | 预处理 | 与 lf-1.6.5 实测的关系 |
|------|--------|------------------------|
| A | uint16 截断 + ROI `/256`→uint8（lf 完整链路） | **完全复现** lf-1.6.5 结果 |
| B | float 全精度（项目链路） | 复现项目软件结果 |
| C | uint16 截断但不 `/256` | ≡ B（截断无影响） |
| D | float + `/256`→uint8 | ≡ A |

**结论：差异 100% 来自 lf-1.6.5 在 ROI 送入引擎前的 `/256 → uint8`
8-bit 量化**（其 find_roi 历史路径遗留）；uint16 截断影响为零。
项目链路保留浮点全精度，数学上更准确（sfrmat5 为超采样算法，输入精度越高
越好）。两者均值差 -0.0001、最大差 0.0027，远小于 MTF 测量不确定度，
PASS/FAIL 判定完全一致。**保持项目现有行为，不做对齐。**

---

## 14. Read Raw 参数精简：移除字节序与黑电平（2026-08-14 新增）

MTF 测试全流程实际不使用这两个参数，从用户界面移除以降低配置负担：

- **字节序**：固定 little-endian（Leopard 相机输出均为小端）；
- **黑电平**：不扣除。MTF 为对比度归一化指标，常数偏移对结果无实质影响
  （lf-1.6.5 的 MTF 链路同样不扣黑电平，见参考文档 §三）；
  且黑电平校正对 MTF 的意义在于暗场/坏点类模块，不属于本流程。

改动范围：

| 文件 | 改动 |
|------|------|
| `iqtest/config/read_raw_settings.py` | `READ_RAW_FIELDS` 移除 `byte_order` / `black_level` 字段（旧设置文件中的这两个键读取时自动忽略） |
| `iqtest/widgets/read_raw_dialog.py` | `config_from_form` 不再传 byte_order/black_level（RawReadConfig 默认 little/0） |
| `iqtest/analysis/mtf_adapter.py` | `load_raw_image` 移除 byte_order/black_level 引用；旧 criteria JSON 中残留的这两个 params 键静默忽略 |
| `iqtest/config/lf_config.py` | Add LF Config 不再导入 `Black_Level`（仅在导入摘要中提示其存在） |

**设置保存位置（同日变更）**：Read Raw 全局设置改存项目内
`assets/config/read_raw_settings.json`（原 C 盘 `~/.leopardiqlts/`）；
旧位置文件在项目文件不存在时自动回落读取，下次保存即写入项目目录。
`LEOPARDIQTS_CONFIG_DIR` 环境变量仍可覆盖（测试隔离用，此时不做旧版回落）。

底层 `leopardiq.utils.raw_reader.RawReadConfig` **保留** `byte_order` /
`black_level` 参数（默认 little / 0.0），供 SFRAnalyzer 等其他算法入口使用。

---

## 15. MTF 结果 CSV 导出（模组比较前置功能，2026-08-17 新增）

为「模组性能比较（MTF）」功能（设计文档
`doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md` §3.2 / §6.1）提供输入：
把 `analyze_mtf` 的结果导出为**带口径元数据的 CSV**，供跨时间/跨机器的
A/B 模组比较加载，同时可直接用 Excel 打开复核。

### 15.1 CSV 格式

单文件 = `#` 元数据头 + 逐 (ROI, 通道) 指标表：

```csv
# LeopardIQ MTF Result CSV
# schema_version: 1
# label: LensA_SN001
# created: 2026-08-17T11:55:00
# image: SN_2-0.6_D_07_28_2026_T_16_37_32.raw
# image_width: 1920
# image_height: 1200
# freq_unit: Cycles/pixel
# freq1: 0.125
# gamma: 1
# pixel_size_um: 2
# picture_height: 1200
roi,channel,cx_norm,cy_norm,valid,mtf@0.125,mtf50,mtf30,mtf50p,mtfa
1,Y,0.502,0.487,1,0.4213,0.1821,0.3105,0.2988,0.0821
```

- 元数据头携带比较所需的全部口径参数（freq_unit / freq1 cy/px / gamma /
  pixel_size_um / picture_height / 图像尺寸），比较时据此做同口径校验；
- 指标列**动态生成**：`mtf@{freq1}` + `mtf50` + 各 Secondary Readout
  （按导出时配置，如 `mtf30`、`mtf50p`）+ `mtfa`；比较功能的可选测试项
  = 两份 CSV 指标列的交集；
- `cx_norm` / `cy_norm`：ROI 中心坐标归一化到图像尺寸（0~1），是比较时
  **按视场位置（中心/四角）匹配 ROI 的唯一依据**（两模组 ROI 坐标不一致，
  坐标匹配无意义）；源数据来自适配器 `details["image_sizes"]`
  （本次新增：图像名 → [W, H]，随图像加载缓存记录）；
- `mtfa`：MTF 曲线下面积（0~Nyquist 梯形积分，`compute_mtfa`），
  导出时趁内存中尚有完整曲线算好——CSV 不含曲线数据，事后无法补算；
- 无效 ROI（引擎失败/预检拦截）：`valid=0`，指标列留空，
  归一化坐标仍保留（供比较时标注排除）；
- `label`：导出时用户填写的模组标签（默认源图像文件名主干），
  逗号/分号/换行会被清洗；文件以 **utf-8-sig（带 BOM）** 写出，
  Excel 打开中文不乱码。

### 15.2 API 与入口

| 项 | 说明 |
|----|------|
| `mtf_export.result_to_csv(result, label="", created=None) -> str` | 纯函数：结果 dict → CSV 文本；无曲线数据抛 ValueError |
| `mtf_export.write_result_csv(result, path, label="") -> Path` | 落盘（utf-8-sig） |
| `mtf_export.compute_mtfa(freq, mtf) -> float` | 0~Nyquist 梯形积分；有效点 <2 返回 NaN；numpy 1.x/2.x 兼容（trapz/trapezoid） |
| `MtfResultView` 工具行「导出结果 CSV…」按钮 | label 输入对话框 → 保存对话框 → 写出，取消不留痕，失败弹窗不崩溃 |

### 15.3 测试与回归

- 新增 `tests/test_m4_1.py`（6 组 **40 断言全部通过**）：格式与元数据、
  数值对拍（容差 1e-6）、归一化坐标、MTFa 手工积分对拍与边界、
  动态 Readout 列、无效 ROI 标记、label 清洗、BOM 落盘往返、
  Figure 按钮端到端（对话框打桩，取消不留痕）；
- 回归：test_m3_1~m3_5（157 断言）、screenshot_m3 冒烟（EXIT=0）全部通过。

```bash
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m4_1.py
```

## 16. MTF 模组比较（2026-08-17 新增）

比较**两款及以上（2~6 款）镜头/模组**的 MTF 结果，输出「谁更好、好多少、
好在哪里」的定量结论。设计文档：
`doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md`（口径校验 §2、视场位置匹配
§3.3、胜负判定与评分 §4、N 款基准金样模式 §4.5）。

**比较功能不重新计算 MTF，只消费 MTF 结果 CSV**（§15 导出）：两次测试的
结果 CSV 随时可加载比较，支持跨时间/跨机器对比（批次抽检、金样比对）。

### 16.1 文件清单

| 文件 | 职责 |
|------|------|
| `iqtest/analysis/mtf_compare.py` | 核心，**纯函数无 GUI**：CSV 解析（`parse_result_csv` / `load_result_csv`）、口径校验（`check_compatibility` / `check_compatibility_multi`）、视场位置匹配（`match_rois` / `match_zones_multi`）、差异 + 胜负 + 分区加权评分（`compare`）、比较结果 CSV 导出（`compare_result_to_csv` / `write_compare_csv`） |
| `iqtest/panels/mtf_compare_panel.py` | `MtfCompareDialog`（Utilities → MTF 模组比较…）：动态槽位 2~6 款 + 基准单选、3×3 配对预览、测试项勾选 + 主判定项、阈值/权重（无箭头直接键入）、嵌入图表（N 折线对比 + Δ 分组条形）、结论区、保存按钮 |
| `iqtest/main_window.py` | Utilities 菜单入口 `_on_mtf_compare_dialog()`（单实例复用） |
| `tests/test_m4_2.py` / `test_m4_3.py` / `test_m4_4.py` / `test_m4_5.py` | 核心 56 断言 / 面板 28 / 图表与保存 24 / N 款比较 32 |
| `scripts/screenshot_m4.py` | 冒烟：两款 + 三款全链路截图（`tests/_m4_smoke/`） |

### 16.2 判定口径速查

- **同口径校验**（不满足禁止比较）：freq_unit / 评估频率 freq1 / Gamma
  必须一致；可选测试项 = 各 CSV 指标列交集；
- **ROI 配对按视场位置**（3×3 九宫格，归一化中心坐标判定），不看像素
  坐标——两模组摆位不同也能正确配对；同位置多 ROI 按到图心距离排序，
  仅一侧存在的 ROI 排除并注记；
- **胜负判定（tie band）**：频率类统一归一化到 cy/px 再比，|Δ| ≤
  tie_freq（默认 0.01，> 测量不确定度 ±0.003）记平手；SFR 类（0~1）
  用 tie_sfr；
- **总体评分**：中心/边缘/四角分区均值加权（默认 0.4/0.3/0.3，
  缺分区剔除后权重归一化；频率类再 ÷ Nyquist 归一），评分差 ≤
  score_tie（默认 0.01）→「两者相当」；
- **跨像元**：两模组 pixel_size_um 不同 → 频率类展示统一换算 LP/mm
  并在结论区警示「仅供参考」；一侧缺像元尺寸则报错禁止比较。

### 16.3 N 款比较（基准金样模式）

- 槽位 2~6 款（「＋ 添加模组 CSV 槽位」/「✕」），单选**基准（金样）**
  （默认槽位 A）；基准排首位，其余各款分别与基准跑一次 pairwise
  `compare()`，共 N−1 组结果，共用同一套阈值/权重/测试项配置；
- 公共视场位置 = 全部 N 款都有数据的 (位置, 通道) 组
  （`match_zones_multi`）；配对预览表逐位置显示各款 ROI 数与公共数；
- 图表：对比图 N 条折线（基准加粗实线，其余按镜头配色轮换线型/符号）；
  Δ 图为**同一张图内每位置 N−1 根并排条形**（各款 − 基准，条形与该
  镜头折线同色；两款时保持红=A 优/蓝=B 优/灰=平手着色）；
- 结论区按「基准（金样）：XXX」+「【各款 vs 基准】」逐款分块；
  保存时两款保存单个 CSV，N 款弹目录选择按
  `MTF比较_{基准}_vs_{各款}.csv` 逐款落盘；
- 局限：只做「各款 vs 基准」，不做非基准款之间的两两比较。

### 16.4 比较结果 CSV

`compare_schema_version: 1`，`#` 元数据头（双方 label、比较配置回显、
逐项统计、总体结论）+ 逐配对行表（每测试项一组 A 值/B 值/Δ/胜负列，
频率类按显示单位），仅单侧 ROI 附表尾标「仅A」/「仅B」；
utf-8-sig 带 BOM。

### 16.5 测试与回归

- test_m4_2（56）/ m4_3（28）/ m4_4（24）/ m4_5（32）全部通过，
  m4_1（40）与 test_m3_1~m3_5 回归无影响；screenshot_m3 / m4 EXIT=0。

```bash
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u tests/test_m4_5.py
QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u scripts/screenshot_m4.py
```

## 17. MTF 模组比较操作步骤（用户视角）

以下按代码实际交互（`main_window.py` / `mtf_compare_panel.py` /
`mtf_compare.py`）梳理一次完整模组比较的操作链路，可作为使用手册与
回归验证清单。

```
（前置）各模组分别完成 MTF 测试（§11 步骤 0~7）
  → 步骤 1：结果 Figure「导出结果 CSV…」（每款模组各导出一份）
  → 步骤 2：Utilities → MTF 模组比较… 打开比较对话框
  → 步骤 3：各槽位「浏览…」载入 CSV（2~6 款），单选基准（金样）
  → 步骤 4：核对状态行（口径）与 ROI 配对预览表
  → 步骤 5：勾选比较测试项、单选主判定项
  → 步骤 6：（可选）调整打平阈值与评分权重
  → 步骤 7：「执 行 比 较」→ 看图表与结论
  →（可选）步骤 8：「保存比较结果 CSV…」落盘
```

### 步骤 1：导出各模组的 MTF 结果 CSV（前置）

每款待比较的模组各做一次 MTF 测试（§11 全流程），在结果 Figure 工具行
点 **「导出结果 CSV…」**：输入模组标签 `label`（默认图像文件名主干，
**建议填镜头型号/序列号**，比较结论与图表图例都用它）→ 选路径保存。
建议导出前在 MTF 参数中填好**像元尺寸**（pixel_size_um）——跨像元
模组比较时用于统一 LP/mm 口径。

> 比较要求各 CSV **同口径**：频率单位、评估频率、Gamma 必须一致
> （§16.2）。请在各次 MTF 测试时使用相同参数配置。

### 步骤 2：打开比较对话框

入口：顶部品牌栏 **🛠 Utilities → MTF 模组比较…**（非模态对话框，
重复打开复用同一实例）。

### 步骤 3：载入 CSV 并选择基准

1. 对话框初始为 2 个槽位（模组 A / B）；比较 3 款以上时点
   **「＋ 添加模组 CSV 槽位」**（最多 6 款），点槽位行尾 **「✕」** 移除
   （至少保留 2 款）；
2. 每个槽位点 **「浏览…」** 选择该款模组的 MTF 结果 CSV；槽位信息行
   显示模组标签与数据行数；
3. **单选「基准」**（默认槽位 A）：基准即金样（Golden Sample），其余
   各款都与它比较；切换基准后状态、预览、图表自动刷新。

### 步骤 4：核对口径状态与配对预览

- 状态行：绿色「口径一致（单位，评估频率，Gamma）；基准（金样）= XXX；
  配对 N 对」表示可比较；红色「口径校验失败：…」按提示排查
  （常见于单位/评估频率/Gamma 不一致）；「请再载入另一份」表示还不够两款；
- **ROI 配对预览表**：3×3 视场位置逐行显示各款在该位置的 ROI 数量与
  公共配对数（青色）；「—」表示该位置无 ROI；配对数为 0 时无法比较。

### 步骤 5：勾选比较测试项、单选主判定项

「3 比较测试项」区列出各 CSV 指标列的**交集**（默认全勾选）：
勾几项就比较几项；**单选「主判定」**（默认第一项）决定顶部总体结论
按哪个指标给出。常用选择：解析力看 MTF50（或 MTFnnP），1/4 Nyquist
处表现看 MTF@0.125，整体能量看 MTFa。

### 步骤 6（可选）：调整打平阈值与评分权重

「4 打平阈值与评分权重」区直接键入数值（无上下箭头）：

- **频率类打平阈值**（默认 0.01 cy/px）：同一位置两款之差 ≤ 此值记平手
  ——MTF 重复测量本身有 ±0.003 量级不确定度，阈值内差异是噪声而非
  真实优劣；**SFR 类打平阈值**（默认 0.01）同理，用于 MTF@freq / MTFa；
- **评分打平阈值**（默认 0.01）：总体评分差 ≤ 此值时结论为「两者相当」；
- **评分权重**：中心/边缘/四角分区权重（默认 0.4/0.3/0.3）。

### 步骤 7：执行比较，读图表与结论

点图表区右上 **「执 行 比 较」**：

- **左图（各款对比）**：横轴 = ROI 视场位置（中心在前，其后四角），
  纵轴 = 所选测试项值；N 条折线，基准加粗实线，图例标注「（基准）」；
  「图表测试项」下拉可切换显示的指标（默认主判定项）；
- **右图（Δ 差异条形）**：各位置「各款 − 基准」并排条形（颜色与折线
  对应；两款时红 = A 优/蓝 = B 优/灰 = 平手）；**±打平阈值虚线**之间的
  差异为噪声级，带外才是真差异；
- **比较结论区**（图表下方）：两款时给出总体结论 + 逐项结论；多款时
  按「基准（金样）：XXX」+「【各款 vs 基准】」逐款分块列出
  （含胜负计数与优势区域）；单边 ROI、跨像元换算在此注记。

### 步骤 8（可选）：保存比较结果 CSV

比较结果**不会自动保存**。点底部 **「保存比较结果 CSV…」**：

- 两款：选路径保存单个 CSV（默认名 `MTF比较_A_vs_B.csv`）；
- 多款：选一个**目录**，按「基准 vs 各款」逐款落盘 N−1 个 CSV
  （`MTF比较_{基准}_vs_{各款}.csv`）；
- CSV 含口径元数据、比较配置回显、逐项统计与逐位置 A/B/Δ/胜负明细，
  Excel 可直接打开（utf-8-sig）。

> 注意：重新载入任一 CSV 或切换基准后，旧比较结果失效——图表清空、
> 保存按钮禁用，需重新执行比较。
