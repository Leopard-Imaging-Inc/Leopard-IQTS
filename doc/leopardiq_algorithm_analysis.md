# LeopardIQ 算法库功能分析文档

> ⚠️ **本文档描述的是旧版模块结构**（`dark/`、`light/`、`sfr/`、`image_quality_all.py` 等），
> 当前代码已重构为 `utils/` / `mtf/` / `shading/` / `flare/` / `fov/` 结构
> （见 `doc/代码优化方案.md` 的「现状架构」）。
> 下方各算法的**原理描述**（坏点 / DSNU / PRNU / SFR / Flare / FOV 等）仍具参考价值，
> 但**文件路径与模块划分**请以当前代码为准。

## 1. 概述

LeopardIQ（leopardiq）是一个面向摄像头模组图像质量评估的 Python 算法库。该库通过对摄像头模组在暗场（dark）和亮场（light）条件下拍摄的图像进行分析，配合 SFR/MTF（空间频率响应/调制传递函数）、FOV（视场角）、Flare（杂散光/眩光）等光学指标的量化计算，实现对摄像头模组图像质量的全面评估。

算法库采用 YAML 配置文件驱动的架构，通过 [image_quality_all.py](../leopardiq/image_quality_all.py) 和 [image_quality.py](../leopardiq/image_quality.py) 作为统一入口，支持多种摄像头型号（hawk、owl、ov2311、ox05b、pi、imx900 等）。

---

## 2. 模块架构

```
leopardiq/
├── image_quality.py          # 单测试项入口（旧版）
├── image_quality_all.py      # 多测试项批量入口（当前主入口）
├── dark/                     # 暗场测试算法
├── light/                    # 亮场测试算法
├── sfr/                      # SFR/MTF 空间频率响应
├── mtf/                      # MTF C++ 计算引擎
├── fov/                      # 视场角计算
├── flare/                    # 杂散光/眩光分析
├── optical_angle_shift/      # 光轴偏心计算
└── utils/                    # 工具函数库
```

---

## 3. 入口与调度机制

### 3.1 主入口函数

[image_quality_all.py](../leopardiq/image_quality_all.py) 是当前主要的批量测试入口，核心函数：

- **`val_image_quality(dir_path, yaml_path, val_key, val_items, debug)`**：遍历指定目录下的所有测试数据文件夹，根据 `val_items` 列表（可包含 `dark`、`light`、`mtf`、`peak`）依次执行各项测试。

- **`image_quality(yaml_data, val_key, dir_name, dir_path, sub_dir, val_items, debug)`**：单次测试调度函数，根据 `val_key`（相机型号）和 `val_item`（测试类型）调度到对应的算法模块。

**支持的相机型号**：`hawk`、`owl`、`ov2311`、`ox05b`、`pi`、`imx900` 等，各型号通过 YAML 配置文件定义传感器参数和评判标准。

### 3.2 测试流程

```
YAML配置 → 图像数据加载 → 算法计算 → 结果判定(PASS/FAIL) → CSV结果保存
```

---

## 4. 暗场测试模块 (dark/)

暗场测试用于评估摄像头在无光照条件下的传感器性能，输入为 8 张暗场 RAW 图像。

### 4.1 暗场坏点检测 — [dark_defective_pixels.py](../leopardiq/dark/dark_defective_pixels.py)

**算法原理**：
1. 对 8 张暗场图像取平均，得到平均图像，按 Bayer 通道拆分
2. 使用 9x9 均值滤波器进行局部平均，得到局部参考图像
3. 计算每个像素与局部均值的偏差：`defect_img = img - area_img`
4. 将偏差大于阈值 `dp_val_min` 的像素标记为坏点
5. 使用连通域分析（`skimage.measure.label`），统计包含 2 个及以上像素的坏点簇（cluster）数量

**输出指标**：
- 暗场坏点总数（defective_pixels）
- 暗场坏点簇数量（defective_clusters）

### 4.2 暗场坏行/坏列检测 — [dark_defective_columns_and_rows.py](../leopardiq/dark/dark_defective_columns_and_rows.py)

**算法原理**：
1. 按通道计算每个通道的黑电平（black level）
2. 计算每行、每列的平均值，减去黑电平得到暗信号偏移量（DS row/col）
3. 统计偏移量超过阈值 `DRow` 的行数为坏行，超过 `DCol` 的列数为坏列

**输出指标**：
- 暗场坏行数（defective_row）
- 暗场坏列数（defective_col）

### 4.3 暗场固定模式噪声 — [dark_fpn.py](../leopardiq/dark/dark_fpn.py)

**算法原理**（分通道计算）：
1. 计算列均值和行均值
2. 计算每个像素与黑电平偏差的均方值，得到**帧空间方差** `frame_var`
3. 计算**列空间方差** `col_var = Σ(ds_col² - frame_var/height) / width`
4. 计算**行空间方差** `row_var = Σ(ds_row² - frame_var/width) / height`
5. 对各自方差取平方根得到对应 FPN 值

**输出指标**（每通道）：
- 列固定模式噪声均值（column_fpn_mean）
- 列固定模式噪声最大值（column_fpn_max）
- 行固定模式噪声均值（row_fpn_mean）
- 行固定模式噪声最大值（row_fpn_max）

### 4.4 暗信号非均匀性 — [dsnu.py](../leopardiq/dark/dsnu.py)

**算法原理**（参考 EMVA 1288 标准）：
1. 计算每个通道的帧间方差 `s2_c`（均值图像的方差减去黑电平补偿后的像素方差）
2. 计算每个通道的时域方差 `sig2_c`（每帧与均值帧差的均方）
3. DSNU = `sqrt(s2_c - sig2_c / frame_qty)`

**输出指标**（每通道）：
- DSNU 值（单位：DN）

### 4.5 时域噪声 — [temporal_noise.py](../leopardiq/dark/temporal_noise.py)

**算法原理**（ISO 方法）：
1. 计算 8 帧的平均图像
2. 计算每帧与平均图像的差分 `diff_imgs`
3. 对每个通道每帧：
   - 计算差分图像的**空间方差**（spatialVar）→ 帧级别时域噪声
   - 计算差分图像列平均的方差（colVar）→ 列级别时域噪声
   - 计算差分图像行平均的方差（rowVar）→ 行级别时域噪声
4. 对所有帧取平均，乘以 `N/(N-1)` 修正因子

**输出指标**（每通道）：
- 像素级时域噪声（tmp_noise_frame）
- 列级时域噪声（tmp_noise_column）
- 行级时域噪声（tmp_noise_row）

---

## 5. 亮场测试模块 (light/)

亮场测试用于评估摄像头在有光照条件下的成像质量，输入为 8 张亮场 RAW 图像。

### 5.1 镜头阴影/相对照度 — [lens_shading.py](../leopardiq/light/lens_shading.py)

**算法原理**：
1. 按 `bin_size` 将图像划分为网格，计算每个网格的平均像素值
2. 用全局最大值做归一化，得到 shading profile（相对照度图）
3. 将图像分为四个象限（TL/TR/BL/BR），分别取每个象限的最小相对照度
4. 对于 Bayer 彩色传感器，额外计算**色差 shading**：Gr/Gb 均值与 R、B 通道的比值偏移

**输出指标**：
- 四角相对照度（ri_tl, ri_tr, ri_bl, ri_br）
- 四角相对照度差异（ri_diff）
- shading profile（用于后续 LSC 校正）
- 红色-绿色偏移（green_red_shift）
- 蓝色-绿色偏移（green_blue_shift）

### 5.2 镜头阴影校正 — [lsc.py](../leopardiq/light/lsc.py)

**算法原理**：
使用镜头阴影分析得到的 shading profile 对图像进行校正：`img_out = img / shading_profile`

### 5.3 光学中心偏移 — [optical_center.py](../leopardiq/light/optical_center.py)

**算法原理**：
1. 将图像转换为亮度图像（luminance）
2. 在图像中心和四角方向各取一个 ROI，计算平均亮度
3. 使用中心 ROIs 和边缘 ROIs 的均值作为阈值，将图像二值化
4. 计算二值图像的重心（通过累积分布函数插值求 50% CDF 位置）
5. 重心与图像几何中心之间的偏移即为光学中心偏移

**输出指标**：
- 光学中心 X 偏移（shift_center_x, px）
- 光学中心 Y 偏移（shift_center_y, px）
- 光学中心偏移距离（oc_shift, px）

### 5.4 脏点与颗粒检测 — [blemish_particle.py](../leopardiq/light/blemish_particle.py)

**算法原理**：
1. 按 `bin_factor` 对亮度图像进行下采样
2. 使用 1x3 中值滤波去除噪声
3. 对中值滤波结果做水平方向相关滤波（`[0.5, 0, ..., 0.5]` 核）
4. 计算差分图像 `diff = (binned - filt) / filt`，取反使得缺陷为正
5. 根据对比度阈值分别检测**脏点**（blemish，大面积低对比度缺陷）和**颗粒**（particle，小面积高对比度缺陷）
6. 使用连通域分析统计满足面积阈值的区域数量

**NaN 处理**：实现了与 MATLAB `medfilt2` 兼容的中值滤波 NaN 处理逻辑——当核窗口含有 NaN 时，输出置为 NaN。

**输出指标**：
- 脏点数量（blemish_count）
- 颗粒数量（particle_count）
- 脏点边界框列表（blemish_box）
- 颗粒边界框列表（particle_box）

### 5.5 亮场坏点检测 — [light_defective_pixels.py](../leopardiq/light/light_defective_pixels.py)

**算法原理**：
1. 对图像进行边缘裁剪（四周裁去 3/11 像素）
2. 使用 9x9 均值滤波器进行局部平均
3. 计算偏差比例 `defect = (img - area) / area`
4. 偏差超过 `hot_percent` 的像素为热坏点（hot），低于 `-cold_percent` 的为冷坏点（cold）
5. 连通域分析统计包含 2 个及以上像素的坏点簇

**输出指标**：
- 冷坏点总数（dp_cold）
- 热坏点总数（dp_hot）
- 冷坏点簇数（cold_clusters）
- 热坏点簇数（hot_clusters）

### 5.6 亮场固定模式噪声 — [light_fpn.py](../leopardiq/light/light_fpn.py)

**算法原理**（分通道计算）：
1. 计算列均值、行均值、帧均值
2. 计算行偏移 `offset_row = row_means - frame_means`
3. 计算列偏移 `offset_col = col_means - frame_means`
4. 帧方差 = `mean((img - frame_means)²)`
5. 行方差 = `mean(offset_row² - frame_var/width)`
6. 列方差 = `mean(offset_col² - frame_var/height)`
7. FPN 值 = `sqrt(方差) / frame_means`（以信号百分比表示）

**输出指标**：
- 帧 FPN（frame_fpn）
- 行 FPN 均值（row_fpn_mean）
- 行 FPN 最大值（row_fpn_max）
- 列 FPN 均值（col_fpn_mean）
- 列 FPN 最大值（col_fpn_max）

### 5.7 光响应非均匀性 — [prnu.py](../leopardiq/light/prnu.py)

**算法原理**（参考 EMVA 1288）：
1. 取图像中心 25% ROI 区域
2. 计算中心平均亮度 `avg_ROI`
3. 计算空间方差 `S2_c = var(img_lsc - avg_ROI)`
4. 计算时域方差 `Sig2_c = var(all_frames - img_lsc)`
5. `PRNU = sqrt(S2_c - Sig2_c/N) / avg_ROI`

**输出指标**（每通道）：
- PRNU 值（百分比）

---

## 6. SFR/MTF 空间频率响应模块 (sfr/)

SFR 模块用于评估摄像头镜头的解析力，支持多种测试标板格式。

### 6.1 SFR Main（多方格标板） — [sfr_main.py](../leopardiq/sfr/sfr_main.py)

适用于 **hawk** 相机型号，使用 e-SFR 风格的多方格标板（9 个方格）。

**算法流程**：
1. **参数初始化**：从配置文件读取频率点、patch 角度、方格位置、尺寸等参数
2. **图像预处理**：读取 RAW 图像，对 Bayer 图像进行通道分离
3. **质心检测**：使用 `get_centroid_hawk()` 检测 9 个方格的中心位置
4. **质心过滤**：通过 `filter_centroid()` 过滤异常质心，验证检测到 9 个方格
5. **边缘搜索**：对每个方格的中心区域，使用二值图像搜索四条边的边缘中心点
6. **ROI 提取**：在每个边缘中心位置提取 SFR 分析 ROI
7. **MTF 计算**：调用 `mtf_sfrmat5_cpp.ComputeMTFArray()` C++ 引擎计算 MTF
8. **结果评估**：与配置文件中的 pass/fail 标准比较

**输出指标**：各频率点处各视场位置的水平和垂直方向 SFR 值、镜头倾斜（Tilt）、MTF 跌落（Falloff）

### 6.2 SFR OV2311 — [sfr_ov2311.py](../leopardiq/sfr/sfr_ov2311.py)

适用于 **OV2311** 相机型号，基于 9 方格标板，对不同角度 patch 计算 SFR。

**核心差异**：质心检测使用 `get_centroid_ov2311()`，支持单通道图像处理。

### 6.3 SFR Cross（十字标板） — [sfr_cross.py](../leopardiq/sfr/sfr_cross.py)

适用于 **owl** 相机型号，使用十字 SFR 标板。

**算法流程**：
1. 根据配置文件确定各图卡位置和 ROI 尺寸
2. 使用 `detect_sfr_cross()` 进行归一化互相关匹配，精确定位十字标板的子区域
3. 对各子区域提取 patch 进行 MTF 计算
4. 计算切向（Tangential）和径向（Sagittal）SFR

**输出指标**：各频率点处各视场位置的切向和径向 SFR 值、镜头倾斜、MTF 跌落

### 6.4 Peak Focus SFR — [peak_focus_sfr_main.py](../leopardiq/sfr/peak_focus_sfr_main.py)

用于确定摄像头模组的**最佳对焦位置**。

**算法流程**：
1. 读取不同距离拍摄的多张 SFR 标板图像
2. 对每张图像的中心 patch 计算多个角度的 MTF 值
3. 取所有 patch 的 MTF 均值作为该距离的 MTF 代表值
4. 绘制 MTF vs 距离曲线，找到 MTF 峰值对应的距离
5. 与目标对焦位置容差比较，判定 PASS/FAIL
6. 如果峰值位置偏差但 Di70 处的 SFR > 峰值的 95%，也判为 PASS

**输出指标**：
- 最佳对焦位置（peak_focus_position）
- MTF vs 距离曲线图（PNG）

---

## 7. MTF C++ 计算引擎 (mtf/)

### 7.1 mtf_sfrmat5_cpp

基于 C++ 实现的 SFR 计算核心引擎，编译为 Python 可调用的 `.pyd` 文件，支持 Python 3.6-3.10 多版本。

**核心函数**：`ComputeMTFArray(sfr_patch, 5, 1.0, False)` — 对 SFR patch 计算 MTF 数组

**算法基础**：ISO 12233 SFR（Spatial Frequency Response）标准中的斜边法，版本 5（sfrmat5）优化。

**优化点**（参考文档 `version5的优化.md`）：
- 优化导数计算精度
- 消除与 MATLAB 结果的差异
- 提升计算效率

---

## 8. FOV 视场角模块 (fov/)

### 8.1 几何法计算 FOV — [calculate_FOV.py](../leopardiq/fov/calculate_FOV.py)

通过已知的相机水平/垂直视距范围和拍摄距离，使用三角函数计算 HFOV、VFOV、DFOV。

**计算方法**：
```
HFOV = 2 * arctan(h_dist / f)
VFOV = 2 * arctan(v_dist / f)
DFOV = norm([HFOV, VFOV])
```

### 8.2 棋盘格法计算 FOV — [FOV_from_832256.py](../leopardiq/fov/FOV_from_832256.py)

通过拍摄棋盘格标板来计算 FOV：

1. 检测棋盘格角点（cv2.findChessboardCorners）
2. 亚像素精度角点优化（cv2.cornerSubPix）
3. 计算水平和垂直方向相邻角点间距
4. 通过已知的格子物理尺寸（grid_size_mm）计算像素到毫米的比率
5. 积分得到图像对应的物理尺寸
6. 使用三角函数计算 HFOV、VFOV、DFOV

### 8.3 Imatest 数据解析 — [getfov_data.py](../leopardiq/fov/getfov_data.py)

从 Imatest 生成的 JSON 文件中解析 FOV 数据（DFOV、HFOV、VFOV），并与 EOL 标准比较。

**评判指标**：
- HFOV / VFOV / DFOV 是否在标准范围内
- 光学中心偏移是否超标

---

## 9. 杂散光/眩光模块 (flare/)

基于 ISO 9358 标准，实现三种眩光测量方法。

### 9.1 测量方法

| 方法 | 适用场景 | 对比度要求 | 所需图像 |
|------|---------|-----------|---------|
| Type A | 可手动曝光 | ≥ 40:1 | 3张（Chart1@H1, Chart2@H2, Chart1@H2） |
| Type B | 不可手动曝光 | ≥ 40:1 | 2张（Chart1@H1, Chart2@H2） |
| Type C | 简化方法 | ≥ 3000:1 | 1张（Chart1@H1） |

### 9.2 核心算法 — [type_flare.py](../leopardiq/flare/type_flare.py)

1. 使用 Hough 圆检测定位测试图卡中的圆形区域
2. 提取黑圆中心区域（黑区）和四周白圆区域（白区）的 Y' luma 亮度值
3. 计算眩光值：`F = Y_Black / Y_White * 100%`
4. Type A/B 方法使用两种曝光下的亮度差进行补偿计算

### 9.3 Type C 简化方法 — [type_C.py](../leopardiq/flare/type_C.py)

仅需一张图像，直接计算黑区亮度与白区亮度的比值。

---

## 10. 光轴偏心模块 (optical_angle_shift/)

### 10.1 [optical_angle_shift.py](../leopardiq/optical_angle_shift/optical_angle_shift.py)

计算光学中心相对于图像几何中心的偏移角度。

**计算流程**：
1. 从相机标定 YAML 文件读取内参（fx, fy, cx, cy）
2. 计算像素偏移：`dx_px = cx - width/2`, `dy_px = cy - height/2`
3. 计算角度偏移：`theta_x = arctan(dx_px / fx)`, `theta_y = arctan(dy_px / fy)`
4. 综合偏移角度：`total_angle = sqrt(theta_x² + theta_y²)`
5. 可选：结合相机规格 FOV，计算相对 FOV 的角度偏移百分比

**输出指标**：
- X/Y 方向像素偏移（px）
- X/Y 方向角度偏移（°）
- 综合角度偏移（°）

---

## 11. 工具函数模块 (utils/)

| 模块 | 功能 |
|------|------|
| [utils.py](../leopardiq/utils/utils.py) | 配置文件加载、图像读取、黑电平计算、均值滤波器生成、质心检测等 |
| [read_image.py](../leopardiq/utils/read_image.py) | RAW 图像读取与解析，支持多种位深 |
| [save_result.py](../leopardiq/utils/save_result.py) | 测试结果 CSV 文件保存 |
| [mtf_utils.py](../leopardiq/utils/mtf_utils.py) | MTF 数据插值（MTF50/MTF30/MTF50P/MTF30P/Nyquist 频率） |
| [sfr_cross_utils.py](../leopardiq/utils/sfr_cross_utils.py) | SFR Cross 参数初始化、MTF 通道计算、patch 结果评估 |
| [sfr_main_utils.py](../leopardiq/utils/sfr_main_utils.py) | SFR Main 参数初始化、ROI 提取、边缘搜索 |
| [dark_utils.py](../leopardiq/utils/dark_utils.py) | 暗场测试业务逻辑封装 |
| [light_utils.py](../leopardiq/utils/light_utils.py) | 亮场测试业务逻辑封装 |
| [len_shading_utils.py](../leopardiq/utils/len_shading_utils.py) | Lens shading mask 生成、bin 图像生成、shading profile 插值 |
| [val_status.py](../leopardiq/utils/val_status.py) | PASS/FAIL 判定逻辑 |
| [bin_image.py](../leopardiq/utils/bin_image.py) | 图像下采样（binning） |
| [line_endpoint.py](../leopardiq/utils/line_endpoint.py) | 线段端点检测 |

---

## 12. 数据流与输出

### 12.1 数据流示意

```
测试图像(RAW) → 图像预处理 → 算法计算 → 结果判定 → CSV 结果输出
                                   ↕
                           YAML/JSON 配置文件
```

### 12.2 结果输出格式

所有测试结果以 CSV 格式保存，包含：
- 测试项名称（save_status_key）
- 测试结果 PASS/FAIL（save_status）
- 测试数据值（data_list）

---

## 13. 支持的相机型号

| 型号 | 支持测试项 | SFR 方法 | 特点 |
|------|----------|---------|------|
| hawk | dark, light, mtf, peak | sfr_main（多方格） | 双目（L/R），Bayer CFA |
| owl | dark, light, mtf | sfr_cross（十字标板） | Bayer CFA |
| ov2311 | dark, light, mtf, peak | sfr_ov2311（多方格） | 单通道，Di70 特定距离 |
| ox05b | light | - | 割草机项目 |
| pi | light | - | 支持 blemish 侧视图 |
| imx900 | light | - | IMX900 传感器 |

---

## 14. 关键技术特点

1. **多传感器适配**：通过 YAML/JSON 配置文件灵活适配不同传感器参数（CFA 排列、位深、分辨率等）和不同评判标准。

2. **MATLAB 兼容性**：算法实现与 MATLAB 参考实现保持高度一致，包括 NaN 处理、边界处理、角标转换等细节。

3. **C++ 加速**：MTF 计算核心使用 C++ 实现并通过 `.pyd` 调用，保证计算效率。

4. **多通道支持**：完整支持 Bayer RGGB 四通道和单通道传感器的图像处理。

5. **模块化设计**：各测试项独立封装，通过统一入口调度，便于扩展和维护。

6. **LSC 集成**：亮场测试可配置是否进行镜头阴影校正后再分析，提升检测准确性。
