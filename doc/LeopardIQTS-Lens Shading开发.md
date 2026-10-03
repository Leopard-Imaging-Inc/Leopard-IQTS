# LeopardIQTS — Lens Shading 模块开发总结

> 对应规划：`doc/LeopardIQTS-IQ测试软件规划.md` 里程碑 **M3（Lens Shading 模块接入，已完成）**。
> 本文档汇总 Lens Shading 功能迄今的全部开发内容：测试方法与 Imatest 对标（§1、§8\~§14）、
> 算法实现（§2\~§7）、开发基线（§16），供后续 Color 比例（M4）、Flare（M5）、FOV（M6）里程碑对照。
> 更新日期：2026-09-29。

***

## 1. Lens Shading 测试是什么

Lens Shading（镜头阴影/暗角）测试，也叫 Shading Test 或 Lens Vignetting（渐晕）测试，
目的是检测镜头光学系统导致画面**从中心到边缘亮度（和颜色）逐渐衰减**的现象。

### 1.1 成因

- **光学渐晕（Optical Vignetting）**：光阑对斜射光线的遮挡，边缘进光量少于中心，符合余弦四次方定律（cos⁴θ）；
- **机械渐晕（Mechanical Vignetting）**：镜筒、光圈叶片等结构件遮挡边缘光线；
- **像素渐晕（Pixel Vignetting）**：光线斜射到 Sensor 像素微透镜上，边缘像素感光效率下降（对 CMOS 传感器尤其明显）。

### 1.2 基本测试方法

1. 模组对准均匀光源（积分球或均匀灯箱，光源均匀性通常要求 >95%）；
2. 拍摄均匀白场 Raw 图；
3. 将画面分成多个区域（13×13、17×17 网格或中心/四角对比），计算各区域平均亮度与中心亮度的比值；
4. 判定示例：四角亮度 ≥ 中心亮度的 55%\~70%（视产品规格而定）。

### 1.3 衍生与用途

- **Color Shading（颜色阴影）**：边缘伴随色偏，通常看各区域 R/G、B/G 比值的一致性；
- 测试结果是 **LSC（Lens Shading Correction）标定**的输入——模组出厂时基于 Shading
  分布烧录校正表（OTP），ISP 据此实时补偿。

### 1.4 常见不良表现

暗角超标、四角亮度不对称（镜头装配倾斜/偏心 tilt/decenter 导致某一角特别暗）、
Color Shading 不均匀等，反映镜头与 Sensor 装配对位不良，是模组制程重要管控项。

***

## 2. 功能概览

Lens Shading（镜头阴影）模块覆盖从原始亮场图到相对照度指标、Color Shading、
LSC 校正表的完整算法链路：

```
RAW 亮场图（多帧平均 / 单帧）
→ Bayer 四通道拆分（或 mono 单通道）
→ 平场掩膜（排除边缘/污染）→ bin 网格分块求均值
→ 归一化 → 四象限 RI（相对照度）→ Color Shading（G/R、G/B 偏移）
→ griddata + RBF 插值生成全分辨率 shading profile
→ 判定（PASS/FAIL）→ 导出（RI 数值表、LSC 校正表）
```

- **相对照度（RI）**：四象限最小值（TL/TR/BL/BR）与四象限差异（ri\_diff），亮度均匀性的核心指标；
- **Color Shading**：Bayer 通道 G/R、G/B 比值的最大最小偏移（green\_red\_shift / green\_blue\_shift）；
- **LSC 校正**：`img_out = img / shading_profile`，输出校正后图像；

模块含两个**显式可选的子功能**（面板「测试项」下拉，`params.test_item`）：

| 子功能         | test\_item       | 内容                                                           | 算法入口                        |
| -------------- | ---------------- | -------------------------------------------------------------- | ------------------------------- |
| 单光源 Shading | `single`（默认） | RI + Color Shading + LSC 闭环验证 + shading\_profile 导出      | `analyze_relative_illumination` |
| 多光源对比     | `multi_light`    | 逐光源分析 + 跨光源一致性（ri\_spread / color\_shift\_spread） | `analyze_multi_light`           |

- 与 NVIDIA EOL 对齐：对应 **Brightfield → Relative Illumination / Color Uniformity / Lens Shading Correction**；
- 测试定义（详 §1）：均匀光源拍白图，量化中心-边缘亮度/颜色差异，兼作 LSC 标定输入。

## 3. 文件清单

| 文件                                         | 职责                                                                                                             |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `leopardiq/shading/__init__.py`              | 模块统一导出（16 个公开函数）                                                                                    |
| `leopardiq/shading/relative_illumination.py` | **单光源 Shading** 子功能：`analyze_lens_shading` / `analyze_relative_illumination`                              |
| `leopardiq/shading/multi_light.py`           | **多光源对比** 子功能：`analyze_multi_light`（逐光源分析 + ri\_spread）                                          |
| `leopardiq/shading/color_uniformity.py`      | Color 比例：`compute_channel_ratios` / `compute_wb_gains` / `compute_color_shading` / `analyze_color_uniformity` |
| `leopardiq/shading/shading_profile.py`       | 掩膜、bin 均值、四象限 RI、通道偏移、shading profile 插值                                                        |
| `leopardiq/shading/lsc.py`                   | LSC 校正：`apply_lsc`                                                                                            |
| `leopardiq/shading/imatest_metrics.py`       | Imatest 对齐指标：`compute_imatest_luma_metrics` / `compute_imatest_color_metrics` / `compute_imatest_metrics`   |
| `leopardiq/utils/image_preprocess.py`        | `split_bayer_channels` / `get_bayer_index` / `bayer_to_luminance`（依赖）                                        |
| `leopardiq/utils/common.py`                  | `create_disk_structuring_element` / `extract_largest_region`（依赖）                                             |
| `iqtest/panels/shading_panel.py`             | Lens Shading 面板（测试项下拉 + 参数 + criteria schema + 图像→光源分配表，M3 接入）                              |
| `iqtest/analysis/shading_adapter.py`         | 面板 → 算法 config 适配器：图像加载、CFA 映射、按 test\_item 分发单/多光源、报告通道、闭环验证                   |
| `iqtest/analysis/shading_export.py`          | shading\_profile 导出（npy/CSV/PNG）与结果 CSV                                                                   |
| `iqtest/figures/shading_figure.py`           | Shading 结果 Figure（RI 热力图 + 四象限数值表 + 逐项判定 + 多光源对比 + 闭环验证 + 可缩放 Luma 等高线）          |
| `iqtest/config/default_criteria.json`        | 模块默认参数与判定阈值                                                                                           |
| `tests/test_phase2_2.py`                     | Phase 2.2 + 2.3 验证测试（5 组 20+ 断言）                                                                        |
| `tests/test_shading_adapter.py`              | M3 适配器验证（CFA/criteria 映射、对拍 1e-6、闭环、多光源、导出）                                                |
| `tests/test_shading_gui.py`                  | M3 GUI 验证（面板/结果视图/主窗口接线，offscreen）                                                               |
| `tests/test_imatest_metrics.py`              | Imatest 口径结果集测试（角区/边区精度、cos⁴ 趋势、Color 比值、mono 降级、NaN 鲁棒性）                            |
| `tests/diag_luma_shading.py`                 | Luma Shading 诊断脚本（归一化基准 / 四象限分层 / LSC 闭环对照，见 §14.6）                                        |

来源：算法提取自 LeopardIQ0529 `leopardiq/light/lens_shading.py` 与
`leopardiq/utils/len_shading_utils.py`（见 `doc/LeopardIQ-leopardiq_algorithm_analysis.md` §5.1）。

## 4. 数据流与算法流程

`analyze_lens_shading()` 核心流程（见 `relative_illumination.py`）：

1. **输入归一**：图像转 `float64`，2D 自动升为 `(H, W, 1)`；
   - Bayer 拆分后 4 通道 `(H/2, W/2, 4)` 或 mono 单通道；多帧由调用方平均；
   - 标准接口 `analyze_relative_illumination()` 支持 RAW 2D 输入自动拆分、多帧列表自动平均；
2. **bin 网格起点**（MATLAB 1-based → Python 0-based 已换算）：
   `start_axisx = floor(mod(width, bin_size) / 2)`，`start_axisy` 同理；
3. **平场掩膜**：按 thresh 生成有效区域，掩膜外像素置 NaN；
4. **分块均值**：以网格点为中心取 `bin_size × bin_size` 邻域求 nanmean（掩膜中心为 0 的网格输出 NaN）；
5. **四象限 RI**：`shading = means / nanmax(means)`，分别取 TL/TR/BL/BR 象限最小值；
6. **Color Shading**（仅 Bayer 4 通道）：由 bin 均值计算 G/R、G/B 偏移；
7. **插值**：`interp_shading_profile()` 生成全分辨率 `(H, W, C)` shading profile。

## 5. 核心算法详解

### 5.1 平场掩膜 `create_flat_field_mask`

- `thresh != 0`：取 **Gr 通道 > thresh** 的区域 → disk(10) 结构元素腐蚀 →
  保留最大连通域（排除图像边缘/污染区域）；
- `thresh == 0`：返回全 1 掩膜（全图有效）。

### 5.2 网格分块均值 `bin_image_means`

- 输入 `axisx/axisy`（网格点坐标）、`bin_size`、图像、掩膜；
- 每个网格点取 `[y ± bin_size/2, x ± bin_size/2]` 邻域（`get_bin_coordinates`，自动裁剪到图内）；
- 输出 `(len(axisy), len(axisx), C)` 均值数组，无效网格为 NaN。

### 5.3 四象限相对照度 `compute_quadrant_ri`

- `shading = final_pv / np.nanmax(final_pv, axis=(0,1))`（按通道归一，中心≈1，边缘<1）；
- 图像按中心分为四象限，各象限取**最小相对照度**为该象限 RI；
- Bayer 时 RI 为 4 通道数组（逐通道），mono 时为标量；
- `ri_diff = max(RI) - min(RI)`（四象限对称性指标，越小越均匀）。

### 5.4 Color Shading `calculate_channel_shift`

```
green_red_shift  = max(|1 - max(G/R) / min(G/R)|)
green_blue_shift = max(|1 - max(G/B) / min(G/B)|)
```

其中 `G = (Gr + Gb) / 2`。反映全画面色彩（色度）随位置的变化，与 NVIDIA
Color Uniformity 的 Gr/R、Gr/B 最大最小偏差评估目标一致。

### 5.5 Shading Profile 插值 `interp_shading_profile`

- **支持外插**（`support_extrapolation=True`，默认）：先 `scipy.interpolate.griddata`
  （linear）整体插值，再用 **RBF**（`interp.Rbf`，linear 核）填补外插区域的 NaN；
  - shading 含 NaN 时：取非 NaN 点插值后，将 NaN 网格辐射区（±bin\_size）重新置 NaN；
- **仅内插**（`False`）：只 griddata，边缘可能含 NaN，速度快、内存省；
- 输出：与原图同分辨率 `(H, W, C)`。

### 5.6 LSC 校正 `apply_lsc`

- `img_out = img / shading_profile`（shading\_profile 中心≈1、边缘<1，除法放大暗角）；
- 分辨率不匹配抛 `ValueError`；
- 修复记录：原实现有硬编码副作用（写 `data/PI/output_image.jpg`），提取后已移除，
  仅返回校正后图像。

### 5.7 RBF 外插 与 LSC 校正的区别

两者处于分析链路的不同位置，作用完全不同，不要混淆：

| 维度     | RBF 外插（§5.5）                         | LSC 校正 `apply_lsc`（§5.6）                  |
| -------- | ---------------------------------------- | --------------------------------------------- |
| 环节     | **测量/建模**：插值生成 shading\_profile | **应用/校正**：使用 shading\_profile 修正图像 |
| 作用对象 | shading\_profile 本身                    | 输入图像 `img`                                |
| 做什么   | 决定 profile 边缘是 NaN 还是被 RBF 补全  | `img_out = img / shading_profile` 把暗角补亮  |
| 影响面   | profile 精度（边缘填充质量）             | 校正后图像 + 闭环残余测试                     |

即：**RBF 外插决定「把 bin 网格插成完整 profile 时边缘如何补全」（建模内参），LSC 决定
「拿到 profile 后是否/如何用它去掉图像暗角」（校正动作）**。二者可独立开关、也可组合使用
（开 RBF 得更完整 profile，再开 LSC 做校正）。两者均属结果界面重算项（见 §16 结果界面后处理组件），**都不改变
主 metrics/pass 判定**（判定始终来自未校正原始图 = 镜头本身状态）。

## 6. Lens Shading 参数解析

### 6.1 面板参数（`iqtest/panels/shading_panel.py`）

| 参数                 | 类型   | 默认   | 说明                                                                           |
| -------------------- | ------ | ------ | ------------------------------------------------------------------------------ |
| test\_item           | choice | single | 子功能：single（单光源）/ multi\_light（多光源）                               |
| grid\_size           | int    | 16     | **网格尺寸**：四象限 RI 的分块粒度（bin\_size，作用于 Bayer 拆分后的计算网格） |
| thresh               | float  | 0.0    | 平场掩膜 DN 阈值（0=全图有效）                                                 |
| gamma                | float  | 1.0    | 输入 Gamma（编码），非 Raw 图按 pixel^(1/Gamma) 线性化；RAW=1.0、sRGB≈0.5      |
| imatest\_report      | bool   | true   | 是否生成 Imatest Uniformity 口径结果集                                         |
| imatest\_block\_size | int    | 32     | **Imatest block 尺寸**（原始像素，\[32x32 pxls areas]）                        |
| corner\_region\_pct  | float  | 0.0    | 角区/边区边长比例；设 0 = 固定 32×32（Imatest 默认）                           |
| contour\_levels      | int    | 10     | Pixel contours 等值线级数                                                      |

判定 criteria：`ri_corner_min` / `lum_uniformity_min` / `green_red_shift_max` / `green_blue_shift_max`。

> 注：Color Shading（R/G、B/G）在线性域由 Bayer 拆分的四通道直接计算
> （`R/G`、`B/G`，G=(Gr+Gb)/2），**不做去马赛克、不做 gamma**——这是与 Imatest
> 对齐后确认的口径（见 §12.3）。

### 6.2 网格尺寸 vs Imatest block 尺寸

两者是**相互独立**的两套分块口径，服务于不同指标：

| <br />   | 网格尺寸 grid\_size                                 | Imatest block 尺寸 imatest\_block\_size               |
| -------- | --------------------------------------------------- | ----------------------------------------------------- |
| 用途     | 四象限 RI（ri\_tl/tr/bl/br、ri\_diff）              | Imatest 对标（Max/Corners/Sides/九点、Color R/G-B/G） |
| 单位     | 拆分后网格像素                                      | **原始传感器像素**                                    |
| 默认     | 16                                                  | 32（Bayer 拆分后按 1/2 换算成 16）                    |
| 生成     | `analyze_relative_illumination` → `bin_image_means` | 复用 `bin_image_means` 改 `bin_size` 再算一次         |
| 是否联动 | —                                                   | 不随 grid\_size 变化，固定用原始 32                   |

关键：`bin_means`（grid\_size 分块）只用于四象限 RI；Imatest 对标用独立网格（原始 32），
二者数据源是同一张已加载图像（`avg`），仅 block 尺寸不同，**不重复读图**。

## 7. 判定标准

面板 criteria → 算法 criteria 由 `iqtest/analysis/shading_adapter.py` 的
`_criteria_from_panel` 映射；Color Shading 判定仅 Bayer 输入生效，mono 跳过。

| 指标           | 算法 criteria 键    | 面板键                              | 判定逻辑                                                     |
| -------------- | ------------------- | ----------------------------------- | ------------------------------------------------------------ |
| 四象限 RI 下限 | `ri`                | `ri_corner_min`（默认 0.70）        | `min(RI) >= ri` → PASS                                       |
| 四象限差异上限 | `ri_diff`           | `lum_uniformity_min`（默认 0.80）   | `ri_diff = 1 - 均匀性`，`ri_diff <= 0.20` → PASS             |
| G/R 偏移       | `green_red_shift`   | `green_red_shift_max`（默认 0.20）  | `<= 阈值` → PASS（仅 Bayer）                                 |
| G/B 偏移       | `green_blue_shift`  | `green_blue_shift_max`（默认 0.20） | `<= 阈值` → PASS（仅 Bayer）                                 |
| 白平衡增益     | `r_gain` / `b_gain` | —                                   | `lo <= gain <= hi` → PASS（`analyze_color_uniformity` 专用） |

`overall_pass = all(metrics PASS)`。

***

## 8. 多光源（"几种光源"）需求

多光源对比已作为 Lens Shading 的**独立子功能**解耦：面板「测试项」选 `multi_light`
即进入多光源对比模式（算法入口 `analyze_multi_light()`，独立文件
`leopardiq/shading/multi_light.py`），通过「图像 → 光源」表逐图指定光源，
跨光源指标 `ri_spread` / `color_shift_spread`。Imatest 推荐的 LED
灯箱也支持可选色温 3100K/4100K/5100K/5500K/6500K/NIR[^1]。

> 解耦说明：多光源不再由"光源数量 ≥2"自动触发，而是显式子功能，与单光源 Shading
> 物理分离（算法层拆到 `multi_light.py`，适配器按 `test_item` 分发）。

### 8.1 含义

在每种标准光源下各拍一张均匀 RAW 图，分别做一遍 Shading 测试，再横向对比：

```
D65 光源 → 均匀白图 → Lum + Chrom Shading 结果₁
TL84 光源 → 均匀白图 → Lum + Chrom Shading 结果₂
A 光源   → 均匀白图 → Lum + Chrom Shading 结果₃
→ 跨光源一致性检查（ri_spread）
```

### 8.2 为什么需要多光源

- **Lum Shading**：由镜头几何光学决定（cos⁴θ、光阑遮挡），与光谱基本无关，一种光源测一次基本够；
- **Chrom Shading**：**强烈依赖光源光谱**——
  1. IR 滤光片角度特性：蓝玻璃 IR cut 截止特性随入射角漂移，光源红光/IR 比例越高（如 A 光源 2856K）边缘色偏越明显；
  2. CRA 与微透镜光谱响应随入射角和光谱变化[^2]；
  3. 结果：D65 合格 ≠ A 光源合格。

### 8.3 工程深层原因：LSC 校正表分色温

模组 LSC 标定通常只在一个色温（如 5100K/D65）进行，但整机 ISP 存储多套 LSC 表（高/中/低色温），运行时按 AWB 估计色温插值切换。若标定光源与实际光源 Color Shading 特性差异大，会出现"标定光源下完美、其他光源下残留色偏"。多光源测试本质是**验证模组全色温范围内 Shading 可控**，保证 LSC 标定策略可行。

### 8.4 项目落地建议

| 需求                | 现状                      | 建议                                             |
| ------------------- | ------------------------- | ------------------------------------------------ |
| 逐光源分析          | ✅ `analyze_multi_light()` | 直接使用                                         |
| 光源定义            | 面板 D65/TL84/A/CWF       | 与客户规格对齐（对应 Imatest 灯箱色温档位[^1]）  |
| 跨光源 Luma 一致性  | ✅ `ri_spread`             | 设规格上限（如 ≤ 0.03）                          |
| 跨光源 Chrom 一致性 | ⚠️ 仅逐光源 shift          | 补 `color_shift_spread`：各光源 shift 的 max−min |
| 每光源 WB 增益      | ✅ `compute_wb_gains`      | 验证增益合理性（A 光源 R 增益应明显小于 D65）    |

***

## 9. 与 Imatest Uniformity 测试的关系

**结论：核心上是同一个测试，但 Imatest 的 Uniformity 模块覆盖面更宽。Lens Shading Test 是 Uniformity 测试中最核心的部分。**

### 9.1 相同部分

Imatest 文档明确：*Uniformity measures lens vignetting (dropoff in illumination at the edges of the image)*[^1]。

- **方法相同**：对准均匀光源拍摄均匀白场图（Imatest 推荐 LED 灯箱，均匀性 90–95%）[^1]；
- **分析逻辑相同**：边缘/四角相对中心（最大值）的亮度衰减比例。Imatest 的 `Corners: worst / mean` 即四角亮度占最大亮度的百分比[^1]；
- **Color Shading 均包含**：Imatest 支持 R/G、B/G、Delta-C 等色彩不均匀性分析[^1]。

### 9.2 不同部分

1. **测试对象更广**：Uniformity 还可测 Sensor 本身均匀性（可不装镜头）、闪光灯照明均匀性、平板扫描仪均匀性[^1]；
2. **附加功能更多**：hot/dead pixel 检测、像素直方图、Grid/Sector 图、细粒度噪声分析等[^1]；
3. **应用阶段不同**：Imatest 多用于整机/研发阶段（输入 JPEG/RAW，引入 gamma、f-stop/EV 概念）；模组厂产线在模组阶段用 Raw 数据测试，还需生成 LSC 校正表烧录 OTP。注意：若整机已开启 LSC 校正，Imatest 测得的均匀性是**校正后的结果**，非镜头本身渐晕。

### 9.3 Imatest 的两张结果图

亮度等高线图与 f 制光圈等高线图是 Lens Shading 结果的**两种等价表达**（同一数据的两种形式）：

- **亮度等高线图（Luminance contour plot）**：归一化相对亮度（最大值 = 1），图下方给出 `Corners: worst / mean` 等判定数据，对应产线"四角/中心 ≥ 某百分比"规格[^1]；
- **f-stop 等高线图**：换算为曝光档数（EV），f-stop loss = log₂(亮度比)，需先用 gamma 将像素值还原为线性亮度（f-stop loss = 3.322 × log₁₀(pixel ratio^(1/γ))），结果依赖正确的 gamma 值[^1]。

**注意**：两张图测的是整个成像链路的总不均匀性（镜头渐晕 + Sensor 像素渐晕 + 光源不均匀度），文档示例图"顶部偏亮"即光源不均匀的痕迹。镜头部分通常占主导，可直接当作 Lens Shading 结果；精确归因需保证光源均匀性并考虑 LSC 是否已启用。

## 10. 测试输入要求

先纠正细节：Imatest 文档原文为 "Save the image as a RAW file or maximum quality JPEG"（RAW 或最高质量 JPEG）[^1]，非 PNG。且 Imatest 面向整机/消费相机，接受的是 demosaic 后的 RGB 图像；模组级测试应更严格。

### 10.1 输入格式优先级

| 输入类型                                                       | 推荐度   | 说明                                                                                                                                         |
| -------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **RAW Bayer 原始数据**（10/12/14bit，raw16/raw10 二进制、DNG） | ✅ 首选   | 线性数据、未经 ISP 处理、可拆 Gr/R/B/Gb 四通道，正是 `analyze_relative_illumination()` 的设计输入（`cfa` 参数）                              |
| Mono 灰度 RAW                                                  | ✅ 可接受 | 只能测 Luma Shading；代码已支持（`cfa: ["Y"]`）                                                                                              |
| 线性 RGB TIFF/PNG（16bit，无 gamma）                           | ⚠️ 可用   | 通道经插值平滑，Color Shading 有轻微误差；可作 Imatest 对标的中间格式                                                                        |
| JPEG / 普通 PNG（8bit，gamma 编码）                            | ❌ 不推荐 | ① gamma 使亮度非线性，比值失真；② 压缩抹掉细节（Imatest 也警告 JPEG smear 坏点、需最高质量）[^1]；③ 整机 JPEG 往往已过 LSC，测的是校正后残留 |

### 10.2 采集硬性条件（比格式更重要）

- **LSC 必须关闭**；
- **固定曝光和增益**，中心亮度建议在满量程 70\~80%（避免饱和、避免太暗被噪声主导）；
- **多帧平均**降噪，建议 8 帧以上（Imatest 测固定模式噪声也建议 ≥8 帧）[^1]，接口已支持图像列表自动平均；
- **光源色温照度固定**（Color Shading 对光谱敏感）；
- **AWB 关闭或固定白平衡增益**。

***

## 11. 输出结果与 Imatest 对标

### 11.1 Luma Shading 映射

| LeopardIQTS 输出                                 | Imatest Uniformity 对应                   | 可比性              |
| ------------------------------------------------ | ----------------------------------------- | ------------------- |
| `ri_tl / ri_tr / ri_bl / ri_br`（四象限最小 RI） | `Corners: worst / mean` + UL/LL/UR/LR[^1] | ⚠️ 定义不同，见 11.3 |
| `ri_diff`（四象限 max−min）                      | 四角值离散度（可从 UL/LL/UR/LR 换算）     | 可换算对比          |
| `shading_profile`（全分辨率归一化分布）          | Luminance contour plot[^1]                | 可视化直接对比      |
| —（未实现）                                      | f-stop 等高线图[^1]                       | 可选补充            |

### 11.2 Color Shading 映射

| LeopardIQTS 输出                         | Imatest 对应                                    | 说明             |
| ---------------------------------------- | ----------------------------------------------- | ---------------- |
| `green_red_shift = \|1 − max/min(G/R)\|` | R/G（或 G/R）pixel ratio 的 max/min[^2]         | 同一量的两种写法 |
| `green_blue_shift`                       | B/G ratio 的 max/min[^2]                        | 同上             |
| `gr_ratio_map / gb_ratio_map`            | Color shading 等高线图[^2]                      | 分布形态对比     |
| —（未实现）                              | Grid plot ΔC/ΔE（CPIQ color variability D）[^2] | CPIQ 认证需补    |

### 11.3 对标的三个坑（重要）

1. **"角落"定义不同，数值有系统性差异**：LeopardIQTS 取整个象限所有 bin 的最小值；Imatest 默认取角落小区域（5% 或 32×32 像素）的平均值[^1]。`ri_tl` 会**系统性低于** Imatest corner mean（最小值 ≤ 区域均值）。对比看趋势一致性和差值稳定性，而非数值相等；严格对齐可调整 Imatest Corner regions 大小，或在 bin\_means 上另算"角落 5% 区域均值"口径。
2. **归一化基准**：双方均除以全图最大值，一致 ✅；但 Imatest ΔC/ΔE 以中心区域为参考[^2]，与 max/min 极值法不同——对比 Color 指标用 R/G、B/G 比值口径，勿混用 ΔC。
3. **亮度通道定义不同**：Imatest 的 Y = 0.2125R + 0.7154G + 0.0721B[^1]，JPEG 输入还带 gamma；LeopardIQTS 为 Bayer 四通道独立或 Gr 通道。对标时给 Imatest 喂**线性 TIFF**（同一 RAW 线性 demosaic 生成、gamma 设 1），使两边同处线性域。

### 11.4 可信度验证方案

1. **合成图验证**（已在做）：构造已知衰减量平场图（如角落 0.7），同时喂两边，验证均恢复 ≈0.7（绝对精度验证，`test_phase2_2.py` \[3/5] 组已覆盖自测）；
2. **实测图交叉验证**：10\~20 颗模组（好/中/差），同一 RAW 走两条链路，判定标准为**相关性与排序一致性（如 Spearman > 0.95）**，而非数值相等；
3. **建立口径偏移表**：记录 quadrant-min RI 与 Imatest corner-mean 的稳定偏移，便于产线规格沿用 Imatest 口径时换算。

***

## 12. Imatest Uniformity 对标：Luma Shading 偏差消除总结

> 更新日期：2026-09-20。目标：使 Lens Shading 的 Luma 指标（Max / Corners / Sides / 九点）
> 与 Imatest Uniformity 模块逐项对齐（相对偏差 ≤ 2%）。

### 12.1 四个关键修复（按发现顺序）

| #   | 问题                               | 根因                                                                                   | 修复                                                                                     |
| --- | ---------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 1   | 满量程错误（Max=59.139 vs 0.924）  | `read_raw` 把 10/12/14-bit 左移到 16bit，但满量程误用 `(1<<bit_depth)-1`（10bit→1023） | 满量程对齐 Imatest 16bit 口径：65535（8bit 保持 255）                                    |
| 2   | block 尺寸偏大（R 边中点偏差 68%） | 复用了四象限 RI 的 `bin_means`（拆分后 32），实际 block 为原始 64×64                   | Imatest 对标用独立网格：复用 `bin_image_means` 以 `imatest_block_size/2`（Bayer=16）重算 |
| 3   | L/R 边中点错位（L 偏暗、R 偏亮）   | block 起点 `mod/2` 在整除时 start=0，边缘 block 被裁剪成半个                           | block 起点改为 `bin_size//2`，首个 block 精确覆盖 `[0, bin_size)`                        |
| 4   | B（下边中点）偏 5.4%               | height 不整除 block（600=37×16+8），block 网格无法对齐下边 ROI                         | Corners/Sides 改用像素级 ROI 均值（`_region_mean_pixels` 直接对 Y 像素切片 nanmean）     |

### 12.2 最终对标结果（1920×1200、角区比例=0）

| 指标          | LeopardIQTS                       | Imatest                         | 绝对差  | 相对偏差     |
| ------------- | --------------------------------- | ------------------------------- | ------- | ------------ |
| Max           | 0.925                             | 0.924                           | 0.001   | 0.1%         |
| Corners worst | 0.0413                            | 0.0403                          | 0.0010  | 2.5%         |
| Corners mean  | 0.0414                            | 0.0407                          | 0.0007  | 1.7%         |
| L / R / T / B | 0.0818 / 0.0540 / 0.5530 / 0.5111 | 0.0814 / 0.0545 / 0.549 / 0.505 | ≤0.0061 | 0.5% \~ 1.2% |

结论：Luma 指标已对齐到 Imatest ±2% 以内；Corners、UL/LL/UR/LR 绝对差均 < 0.005 达标。

### 12.3 Color Shading 口径确认（Bayer 拆分 + 线性）

通过 Bayer 拆分四通道原始 DN 值定位（1920×1200、角区比例=0）：

| 位置 | 四通道 DN（Gr/R/B/Gb）            | R/G                                      |
| ---- | --------------------------------- | ---------------------------------------- |
| 中心 | 62876 / 53538 / 43927 / 63486     | 53538 / ((62876+63486)/2) = **0.847**    |
| 角区 | 2726.8 / 2715.8 / 2718.5 / 2735.8 | 2715.8 / ((2726.8+2735.8)/2) = **0.994** |

Imatest 对应值：中心 C=0.848、角区≈0.967，与 Bayer 拆分的线性 R/G 一致。

由此确认 Imatest 的 Color Shading 口径为：**R/G、B/G 由 Bayer 拆分的四通道直接
计算（G=(Gr+Gb)/2），线性域（不做 gamma），不做去马赛克**。之前误用的
「去马赛克 RGB + gamma」导致方向相反（OpenCV 双线性去马赛克把角区 R 抬高），已改回。

最终对标结果（1920×1200、角区比例=0）：

| 指标                        | LeopardIQTS                   | Imatest                       | 差异       |
| --------------------------- | ----------------------------- | ----------------------------- | ---------- |
| R/G max / min               | 1.007 / 0.755                 | 1.01 / 0.755                  | ≤0.3%      |
| R/G 中心 C / 上边中点 T     | 0.848 / 0.795                 | 0.848 / 0.795                 | 0%         |
| R/G 角区 UL/LL/UR/LR        | 0.993 / 0.998 / 0.998 / 0.999 | 0.967 / 0.952 / 0.994 / 0.974 | 0.4%\~4.8% |
| corner/center R/G、B/G、R/B | 1.171 / 1.431 / 0.819         | 1.12 / 1.39 / 0.782           | 2.9%\~4.7% |

结论：Color Shading 的 **max/min、中心、上下边中点已 0\~0.3% 对齐**；角区及由它
派生的 corner/center 有约 **3\~5% 固定偏差**，源于 Bayer 拆分（无去马赛克）与
Imatest 专有去马赛克算法的差异，属可接受的近似（角区 ±5% 内），已接受现状。

***

## 13. LSC 校正表功能定位

### 13.1 两个概念区分

| <br />   | Lens Shading 测试                       | LSC 标定（生成校正表）           |
| -------- | --------------------------------------- | -------------------------------- |
| 目的     | 判断模组**好不好**（PASS/FAIL）         | 生成数据**修好**模组             |
| 输出     | RI、shift 指标 + 判定结论               | 写入 OTP / 给 ISP 的校正表       |
| 产业位置 | IQ 评价工具（对标 Imatest、NVIDIA EOL） | 产线标定站（burning station）    |
| 数据流向 | 模组 → 报告                             | 模组 → 表 → 回写模组，随产品出货 |

LeopardIQTS 定位 IQ 测试软件，**给出可信测试结果是底线任务**。

### 13.2 项目的有利条件

算法链路已具备 LSC 核心能力：

```
bin 网格均值 → 归一化 shading → griddata + RBF 插值
→ 全分辨率 (H, W, C) shading_profile  ← 即 LSC 校正表的"满分辨率版本"
→ apply_lsc: img_out = img / shading_profile
```

从测试结果到 LSC 表只差格式转换（降采样到 ISP 网格、定点量化），M3 规划"LSC 校正表导出"合理。

### 13.3 核心价值：闭环验证

```
测出 shading_profile → apply_lsc 校正 → 对校正后图像再跑一遍 Shading 测试
→ 残余 RI 应接近 1、残余 shift 应接近 0
```

价值：

1. **自证算法正确性**：残余不接近 0 说明 profile 生成或插值有 bug，比合成图更强的验证；
2. **回答客户下一个问题**："暗角能校到什么程度？"——现场给出"校正后四角从 62% 提升到 98%"的量化答案。这是 Imatest 不具备的能力（只测不校）。

> 校正后数字怎么读、ri\_diff 口径差异与常见误区见 §14。

### 13.4 边界：项目的表 ≠ 可烧录的产线 OTP 表

生成真正烧入 OTP、给特定 ISP 用的表还需：各家 ISP 的 LSC 表格式适配（网格数、通道排布、定点位数、色温插值）、与 ISP shading 校正算法对齐、多色温表生成策略。这属于标定工具范畴（模组厂产线软件或 ISP 厂商工具），初期不建议承诺。

### 13.5 功能分层建议

```
必须做（M3 内）：
├── Shading 测试结果（RI / shift / PASS-FAIL）     ← 本体
└── 闭环验证：apply_lsc 后残余 Shading 再测        ← 低成本高价值

建议做（M3 或 M4）：
└── shading_profile 导出（通用格式：npy / CSV / 图）
    定位"供客户参考的校正数据"，非"可烧录 OTP 表"

暂不做（等明确客户需求）：
└── 特定 ISP 格式的 OTP 校正表生成
```

### 13.6 LSC 功能的最终定位

两个用途，**自检为主、参考为辅**：

- **用途一：闭环自检（核心，对内）**：验证 shading profile 生成链路正确性；升级报告说服力（"FAIL 是装配问题而非不可校正缺陷"）。不依赖外部格式对接，M3 可落地；
- **用途二：参考数据导出（次要，对外）**：交付时明确边界——✅ "基于测试数据的校正参考，供 tuning 团队参考"；❌ 不得宣称"可直接烧录的生产用表"；
- **升级判断标准**：当客户拿着其 ISP LSC 表格式规范来对接时，再将"OTP 表生成"正式立项（M4 或更后），做格式适配与验证。在此之前不主动承诺。

***

## 14. LSC 闭环数值判读与常见误区（实测补充）

> 本节由两张实测实验总结而来：**真实 AR0234 图**（1920×1200 / 10bit / GRBG，
> 中心强亮斑光场，中心≈60000DN、四角≈2700DN，衰减约 22 倍）与
> **「中央 24×24 热点合成图」**（其余区域正常 ~205DN，热点 63000DN）。用于解答
> 四象限 RI / ri\_diff 读数中的典型困惑。

### 14.1 RI 与 ri\_diff 是正交指标，不要互相推断

| 指标         | 定义                                           | 反映什么                         |
| ------------ | ---------------------------------------------- | -------------------------------- |
| RI（单象限） | 该象限最暗 bin 相对**全局最大 bin** 的相对照度 | **绝对衰减深度**（四角到底多暗） |
| ri\_diff     | 四个象限 RI 的 max−min                         | **四角衰减的一致性**（对称性）   |

**ri\_diff 小 ≠ 四角亮**。真实 AR0234 图：四角 RI≈0.045 且彼此几乎相等
（TL=0.0449 / TR=0.0447 / BL=0.0446 / BR=0.0447）→ ri\_diff=0.0002。
正确读法：**这张图四角暗得一致（对称性好），但绝对照度只有中心的 4.5%**。
RI 判断暗角深度，ri\_diff 只判断暗角是否对称，二者不可互推。

### 14.2 归一化基准对「热点/过曝块」高度敏感

`shading = bin_means / nanmax(bin_means)` 用**全局单点最大值**归一化（`compute_quadrant_ri`）：
若图中存在过曝热点（反光、亮块、坏点），该点垄断 nanmax，整幅 shading\_map 被压矮，
四角 RI 可能掉到 0.005 量级；且因为**四角都被压得一样矮**，ri\_diff 反而极小——
数值上看起来像"均匀"，实际是"全都暗"。

判读方法：看 shading\_map 最大值所在网格的 **3×3 邻域均值**。
- 热点：max=1.0 但 3×3 邻域均值远小于 1（合成实验：0.117），四角 RI≈0.005；
- 真实亮斑：3×3 邻域均值≈1（AR0234 实测 0.997），四角 RI≈0.045 是真实光场衰减。

### 14.3 校正后图片「中间变暗、边角变亮」是显示归一化观感

`apply_lsc` 即 `img / profile`（中心≈1、边缘<1），数学上**只放大四角，中心不变**。
但校正图的显示/导出按 `(min, max)` 自动归一化：四角被补亮后全图直方图收窄上移，
中心相对新最大值的位置变了，观感"变暗"。判断要用**像素值**（校正前后中心应基本不变），
不要用归一化后的观感。

### 14.4 校正后 ri\_diff 反而变大的机理（不是 bug）

- 校正前"四角都暗"→ 四角 RI 离散度极小（0.0002）；
- 校正后四角被补到 0.87~0.93 → 此时四角**残余不一致**浮现（AR0234：TL=0.886 /
  TR=0.928 / BL=0.892 / BR=0.921 → ri\_diff≈0.042），来源是四角 profile 插值误差
  （griddata 四角外插区）与光场本身非对称（中心亮斑不在画面正中心）；
- 因此**看 LSC 效果应看「校正后最差 RI」的提升与残余判定**，而不是盯 ri\_diff 变大；
- RBF 外插对"中心强亮斑近常数光场"收益有限，甚至 after\_ri\_min 略降
  （实测 RBF 开 0.844 < 关 0.875）——近常数场 RBF 易过冲。

### 14.5 两套 ri\_diff 口径：算法口径 vs Y 报告口径

LSC 验证里同时出现两个 ri\_diff，**定义不同，不可直接比较**：

| 位置                                  | 口径           | 内容                                                                              |
| ------------------------------------- | -------------- | --------------------------------------------------------------------------------- |
| 残余对比 tab（before/after ri\_diff） | **算法口径**   | 4 通道 × 4 象限共 16 个 RI 的 max−min，**含 Color Shading 跨通道差**              |
| 四象限 RI / 校正后四象限 RI tab       | **Y 报告口径** | 先合成 BT.709 Y（G 权重 71%）单通道，再取四象限 RI 的 max−min，**只含亮度均匀性** |

两者差值即色彩（通道间）分量：例如 before 算法 0.0186 − Y 报告 0.0002 ≈ 0.018
为 Color Shading 贡献；after 算法 0.0675 − Y 报告 0.0417 ≈ 0.026 同理。Bayer
彩色输入时算法口径恒 ≥ Y 报告口径；mono 输入二者一致。

### 14.6 诊断脚本 `tests/diag_luma_shading.py`

四角 RI / ri\_diff 异常时，按此排查归一化基准与光场：

```
python tests/diag_luma_shading.py <图像> [--cfa GRBG] [--width 1920]
        [--height 1200] [--bit 10] [--bin 16] [--thresh 0]
```

不传参时 `.raw` 读取软件已保存的 Read Raw 全局设置（本项目该机为
1920×1200 / 10bit / GRBG）。脚本输出：shading\_map 归一化基准（max 位置 +
3×3 邻域均值）、四象限分层 min、低照占比、原图像素级中心/四角均值、
RBF 开/关下 LSC 闭环四象限对照。

***

## 15. 结论速查

| 议题                  | 结论                                                                                                                           |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Lens Shading 测试定义 | 均匀光源拍白图，量化中心-边缘亮度/颜色差异，兼作 LSC 标定输入（§1）                                                            |
| 与 Imatest 关系       | 核心是同一测试（vignetting + color shading），Imatest 覆盖面更宽（含 Sensor 均匀性、坏点、噪声）（§9）                         |
| 亮度/f-stop 等高线图  | 同一 Shading 结果的百分比形式与曝光档数形式（§9.3）                                                                            |
| 测试输入              | 首选 LSC 关闭的 RAW Bayer 多帧平均图；JPEG 不推荐（§10）                                                                       |
| 输出对标 Imatest      | 四象限 RI ↔ Corners 百分比；G/R、B/G shift ↔ 通道比值 max/min；对齐角落定义、线性域、亮度通道三口径；以相关性判定可信度（§11） |
| Imatest 对标结果      | Luma（Max/Corners/Sides/九点）±2% 内；Color Shading max/min、中心 0~0.3%，角区 3~5% 固定偏差已接受（§12）                      |
| 多光源需求            | 每光源各测一遍；Lum 验证一致性，Chrom 逐光源卡规格；根源是 LSC 表分色温（§8）                                                  |
| LSC 表功能            | 现阶段 = 闭环自检 + 校正效果演示（参考数据），非产线标定工具（§13）                                                            |

***

## 16. 当前状态与后续规划（M3 已接入）

**已完成（M3 + Imatest 对标 + 图示优化，更新日期 2026-09-24）**：

- 算法库全部提取并验证（RI、Color Shading、LSC、多光源），panel 与默认配置 schema 就绪；
- **多光源解耦为独立子功能**：算法层 `analyze_multi_light` 拆至 `leopardiq/shading/multi_light.py`；
  面板「测试项」下拉（`test_item`：single / multi\_light）切换，适配器按 `test_item` 显式分发；
  单光源模式取消 `light_source` 指定（不绑定具体光源）；
- **结果界面后处理组件 + 深色字体**：`ShadingResultView` 保持浅色主题，三个 tab 页内容用深色字体；RBF 外插、
  LSC 闭环验证（默认关闭）、亮度通道（Y/G/Gr）自面板移至结果界面，由
  `recompute_single` 驱动即时重算（改报告展示/闭环/profile，不改主判定）；
- Shading 全流程闭环：图像载入（`.raw` 走 Generalized Read Raw、常见格式走 mono 灰度）→
  参数与 criteria 表单（含「图像 → 光源」分配表）→ ANALYZE →
  RI 热力图 + 四象限数值表 + 逐项 PASS/FAIL 判定（`iqtest/figures/shading_figure.py`）；
- 面板参数 → 算法 config 适配器（`iqtest/analysis/shading_adapter.py`），CFA 位置序映射为
  `["R","Gr","Gb","B"]` 四通道名，`bin_size = grid_size`、`thresh` 直通；
- LSC 校正表导出（`iqtest/analysis/shading_export.py`：npy / CSV / PNG，通用参考数据，非 OTP 表）；
- 多光源对比视图（`analyze_multi_light` + 适配器补算 `color_shift_spread`，§8.4）；
- 闭环验证：`apply_lsc` 后残余 Shading 再测（§13.3，单光源，由结果界面「使用 LSC」控制展示）。
- **Imatest Uniformity 口径对齐（2026-09-20，详见 §12）**：
  - 新增 Imatest 指标模块（`leopardiq/shading/imatest_metrics.py`）+ 面板参数
    `gamma` / `imatest_report` / `imatest_block_size` / `corner_region_pct` / `contour_levels`（见 §6.1）；
  - Luma（Max / Corners / Sides / 九点）对齐到 ±2% 以内、Corners 绝对差 < 0.005（§12.2）；
    Color Shading 的 max/min、中心与上下边中点 0~0.3% 对齐，角区 3~5% 固定偏差已接受（§12.3）；
  - Y 亮度通道改用 Imatest 系数 `0.2125R + 0.7154G + 0.0721B`（见 §11.3/§12.3）。
- **结果界面图示优化（2026-09-24）**：
  - 原始 RAW 图示由马赛克灰度改为 **demosaic 后的彩色图**；
  - Imatest Luma 等高线改用同一份修改后的原始 RAW 图数据，支持**滚轮缩放 / 左键拖拽平移 / 双击复位**
    （`_make_zoomable_canvas`），等高线等级设为 [0.125, 0.995] × 峰值；
  - LSC 校正图像按原始 RAW 全分辨率灰度显示（左侧图区下拉列表切换）。

验证：`tests/test_phase2_2.py`（算法回归 25 断言）+ `tests/test_shading_adapter.py`
（40 断言：CFA/criteria 映射、mono/Bayer 单光源与算法接口对拍 1e-6、闭环默认关闭、
`recompute_single` 重算、多光源、光源不足报错、默认 test\_item、导出）+ `tests/test_shading_gui.py`
（25 断言：面板测试项显隐、浅色结果视图 + tab 深色字体、LSC 默认关闭、亮度通道/RBF/LSC 组件
与即时重算、主窗口接线，offscreen）+ `tests/test_imatest_metrics.py`（7 组：角区/边区区域均值精度、
cos⁴ 趋势、文本块格式、Color 比值与 corner/center、mono 降级、NaN 鲁棒性、统一入口）；
另有 `tests/diag_luma_shading.py` 诊断脚本（见 §14.6）。

**待后续里程碑**：Color 比例（M4）、Flare（M5）、FOV（M6）；黑电平标定扣除、
特定 ISP OTP 表格式、CPIQ ΔC/ΔE、f-stop 等高线图按 §10.2/§13.4/§13.5 边界暂不纳入。

> 注：`iqtest/main_window.py` 已注册 shading 结果视图；Lens Shading 不再列为「待实现功能」。

***

## 参考来源

[^1]: Imatest — Using Uniformity, Part 1: <https://www.imatest.com/support/docs/2021-2/uniformity/>

[^2]: Imatest — Using Uniformity, Part 2 (Color shading / Grid plot / CPIQ): <https://www.imatest.com/support/docs/2021-2/lightfall_master/#shading>