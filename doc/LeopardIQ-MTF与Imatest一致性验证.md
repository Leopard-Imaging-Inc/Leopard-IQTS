# LeopardIQ — MTF 测试流程与 Imatest 一致性验证总结

> 本文档汇总 2026-08-21 对 MTF 测试链路与 Imatest 一致性问题的分析、数值验证与结论，
> 覆盖：`reference/mtf_test.py` 流程解析、去马赛克算法对比、Bayer 格式影响、
> 真实 Bayer 格式的独立判定方法、以及偏差统计方法的讨论。
> 验证脚本：`reference/mtf_test_dcraw.py`、`reference/bayer_swap_check.py`。

---

## 1. 背景与目的

项目使用自研 MTF/SFR 测试链路（sfrmat5 C++ 引擎），需要与商业软件 Imatest 的
结果对齐。验收标准初版为**逐 ROI 平均相对偏差 ≤ 1%**，2026-08-21 讨论后建议
放宽为**平均 ≤ 2% + 单点 ≤ 3~4%**（依据与权衡见 §7.4）。围绕以下几个问题展开分析：

1. `reference/mtf_test.py` 的图像处理流程是否合理（RAW → demosaic → 灰度 → SFR）；
2. 与 Imatest 的典型配置（Bilinear、MTF@0.125、Y channel、Gamma=1、sfrmat5 引擎）
   是否实质等价；
3. 去马赛克算法（OpenCV vs dcraw/LibRaw）是否导致偏差；
4. Bayer 格式选错（GRBG vs GBRG）对 Y-channel MTF 的影响；
5. 如何**独立于 Imatest** 判定一张 raw 的真实 Bayer 格式；
6. 偏差统计方法的选择。

---

## 2. `reference/mtf_test.py` 图像处理流程解析

脚本链路（见 [mtf_test.py](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py)）：

```
图片路径 + ROI(y1,y2,x1,x2)
  → RAW/YUV 预处理 → 去马赛克 → 灰度化(BT.709)
  → 按 ROI 直接剪切 → ComputeMTFArray(SFR) → get_mtf 提取指标
```

关键实现：

| 环节     | 实现                                                                                  | 位置                                                                                                      |
| -------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| RAW 读取 | `np.fromfile` uint16 + `left_shift(16-bits)` 补位                                     | [mtf_test.py:L56-L71](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L56-L71)     |
| 去马赛克 | `raw_to_debayer` → `cvtColor(frame, code=47)`（COLOR_BayerGB2BGR = **GRBG，双线性**） | [mtf_test.py:L68-L69](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L68-L69)     |
| 灰度化   | **BT.709 加权** `0.2125R + 0.7154G + 0.0721B`（输入为 BGR 顺序）                      | [mtf_test.py:L79-L84](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L79-L84)     |
| ROI 剪切 | `roi = gray[y1:y2, x1:x2]`（**从灰度图剪切，不是彩图**）                              | [mtf_test.py:L103](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L103)           |
| 位深降维 | 16bit → `/256` 转 uint8                                                               | [mtf_test.py:L107-L108](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L107-L108) |
| SFR 引擎 | `mtf_sfrmat5_cpp.ComputeMTFArray(roi, 5, 1.0, False)`（ISO 12233 sfrmat5）            | [mtf_test.py:L112-L113](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L112-L113) |
| 指标提取 | `get_mtf(mtf_array, *mtf_flag)`，mtf_type=6 → Nyquist25 = 0.125 cy/px                 | [mtf_test.py:L115-L118](file:///f:/project/python/LeopardIQTest_Software/reference/mtf_test.py#L115-L118) |

> 说明：`color_img`（彩色图）仅用于叠加 ROI 框与文字（`draw_results`），**不参与 MTF 计算**。
> 注意：`mtf_test.py` 顶部 `from leopardiq.utils.mtf_utils import get_mtf` 在当前仓库中
> 实际不存在（该导入在参考脚本中会失败）；主项目真正的指标提取在
> [mtf_calculator.py](file:///f:/project/python/LeopardIQTest_Software/leopardiq/mtf/mtf_calculator.py) 的 `compute_mtf_metrics`。

---

## 3. 主项目流程与 Imatest 配置逐条对照

主项目（`leopardiq` + `iqtest` GUI）的 MTF 链路与 Imatest 典型配置对照：

| Imatest 设置                        | 主项目实现                                                                                                                         |          满足          |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | :--------------------: |
| 可调 Bayer 格式 + Demosaic Bilinear | Utilities → Generalized Read Raw 的 `CFA pattern`（Y/RGGB/BGGR/GRBG/GBRG）；`cv2.demosaicing(mosaic, COLOR_BayerXX2BGR)`（双线性） |           ✅            |
| 可设 MTF @0.125 C/P                 | MTF 面板「评估频率 MTF @ (cy/px)」默认 0.125，频率单位可切 Cycles/pixel                                                            |           ✅            |
| Channel = Y/G → 灰度图              | 所有 Bayer CFA 只输出单通道 Y（BT.709）；**无 G-only 选项**                                                                        | ✅（Y 等价；无 G-only） |
| Gamma (input) = 1                   | MTF 面板「Gamma (input)」默认 1.0，线性 RAW 不线性化；算法层 `pixel^(1/gamma)`                                                     |           ✅            |
| sfrmat5 C++ 引擎                    | `mtf_sfrmat5_cpp.ComputeMTFArray(roi, c=5, alpha=1.0, est_angle=False)`                                                            |           ✅            |

**结论：主项目 MTF 链路与 Imatest 配置实质等价。** 仅有两处细微差别：
1. 主项目用 `cv2.demosaicing`（参考脚本用 `cv2.cvtColor`），两者同为 OpenCV 双线性，结果一致；
2. 主项目无 G-only 通道，固定 BT.709 luma。

---

## 4. 去马赛克算法对比（OpenCV vs LibRaw）

目的：验证偏差是否由去马赛克算法导致。

方法（`reference/mtf_test_dcraw.py`）：
- 把裸 Bayer dump 打包成**最小 DNG**（GRBG、黑电平 0、白电平 65535、单位色矩阵）；
- 用 rawpy(LibRaw) 以 LINEAR / VNG / PPG / AHD 四种算法去马赛克；
- `postprocess` 关闭白平衡/色矩阵/gamma/亮度自适应，只保留去马赛克插值本身；
- 其余链路与 mtf_test.py 完全一致（BT.709 luma → ROI → /256 → C++ SFR → Nyquist25）。

### 老图结果（SN_0.65_D_07_30_2026，GRBG，10 个 ROI）

|                    算法 |   mean | 与 Imatest 差 mean / max | **逐 ROI MAPE** | max 单点 |
| ----------------------: | -----: | -----------------------: | --------------: | -------: |
|            Imatest 参考 | 0.6718 |                        — |               — |        — |
| OpenCV cvtColor（现状） | 0.6753 |         +0.0035 / 0.0143 |       **0.99%** |    2.10% |
|           LibRaw LINEAR | 0.6720 |         +0.0002 / 0.0170 |           1.04% |    2.51% |
|              LibRaw VNG | 0.7179 |         +0.0461 / 0.0778 |           6.80% |    9.70% |
|              LibRaw PPG | 0.7500 |         +0.0782 / 0.0998 |          11.65% |   13.21% |
|              LibRaw AHD | 0.7512 |         +0.0794 / 0.1023 |          11.86% |   14.13% |

> **注意统计口径**：`与 Imatest 差 mean / max` 是**绝对差**；
> `逐 ROI MAPE` = mean(|项目_i − Imatest_i| / Imatest_i)，**正负偏差不抵消**，
> 才是验收标准口径。早期的"约 0.5%"是整体均值相对差（|mean(项目)−mean(Imatest)|/mean(Imatest)），
> 会因正负抵消而**严重低估**，已废弃。

**结论：偏差不是去马赛克算法导致。** 去马赛克算法确实改变 MTF（双线性 → AHD 抬高
约 +0.076），但方向是**抬高**；Imatest 参考与当前 OpenCV 双线性链路最接近（逐 ROI MAPE
**0.99%**，max 单点 2.1%，临界压线）。即：双线性 + sfrmat5 引擎的组合在该图上最贴合 Imatest 输出。

---

## 5. Bayer 格式 GRBG vs GBRG 对 Y-channel MTF 的影响

### 5.1 理论

GRBG 与 GBRG 的区别仅在于 **R 和 B 互换，G 像素位置完全不变**。

- 选 Y = 0.2125R + 0.7154G + 0.0721B；把 GBRG 误当 GRBG 解马赛克得
  Y′ = 0.2125B + 0.7154G + 0.0721R；
- 两者之差 = **0.1404 × (R − B)**；
- **G-only 通道完全免疫**（G 位置相同，解马赛克后逐像素一致，已实测 max diff = 0）；
- 理想灰阶目标下 R≈B，故 Y 影响趋近 0；但真实场景中光源偏色 + 斜边边缘色差（CA）/
  解马赛克伪彩会使 R≠B，影响不可忽略。

### 5.2 实测（新图 SN_2_D_08_20_2026，Y channel，MTF@0.125）

|                         指标 |      GRBG |                 GBRG | Imatest |
| ---------------------------: | --------: | -------------------: | ------: |
|               mean（10 ROI） |    0.6986 |               0.6726 |  0.6688 |
| 与 Imatest 差 mean（绝对差） |   +0.0297 |              +0.0037 |       — |
|  与 Imatest 差 max（绝对差） |   +0.0668 |              +0.0299 |       — |
|              **逐 ROI MAPE** | **5.43%** |            **1.71%** |       — |
|             max 单点相对偏差 |     ~8.4% |                ~4.8% |       — |
|   GRBG vs GBRG 差 mean / max |         — | **−0.026 / −0.0534** |       — |

> 注：新图 IQTS 软件 CSV 报告的逐 ROI MAPE = **1.60%**，与本脚本 1.71% 吻合
> （差异来自 ROI 边界差 1 像素）。

R−B 实测（uint16 线性域，满量程 65535）：
- 老图：ROI 内 |R−B| mean ≈ 1900，max 达 1.4万~1.8万 LSB（21~27% 满量程）；
- 新图：ROI 内 |R−B| max 达 1.2万~2.0万 LSB。

**结论：选错 Bayer 对 Y-channel MTF 有显著影响（GRBG vs GBRG 差异约 3~5%）。**
按逐 ROI MAPE：新图正确 CFA（GBRG）**1.71% 仍超 1% 验收线**，错误 CFA（GRBG）5.43%。
G-only 通道则完全不受影响。

### 5.3 与 Imatest 吻合 → 判定真实 Bayer？—— 循环论证，不能

老图（项目/Imatest 都用 GRBG）与新图（都用 GBRG）偏差都小，这**只证明了
"项目链路 ≈ Imatest（在相同 Bayer 设置下）"**，是循环验证，
**无法判定哪个是真实 Bayer**。真实 Bayer 必须用独立证据（见 §6）。
（早期表述的"0.4~0.5%"为整体均值相对差口径，低估，已废弃，正确数字见 §4/§5.2 的逐 ROI MAPE。）

### 5.4 实用推论

「跑两种 CFA vs Imatest 参考」只能用于**确认链路等价性**，不能用于判定真实 Bayer。
真实格式判定需独立证据：
1. 色卡对照（人眼先验，前提：对照时未叠加白平衡/色彩矩阵）；
2. 已知标准光源色温 + 灰阶卡（正确 CFA 下 R≈B≈G）；
3. 已知 sensor 型号/资料。

---

## 6. 真实 Bayer 格式的独立判定方法

不依赖 Imatest，直接统计 **raw mosaic 2×2 四角的原始均值**（平坦区、无插值）。

### 方法

把 mosaic 按 `(y%2, x%2)` 分成 4 类像素，在**亮度适中（30~80% 满量程）且低方差**
的平坦区统计每类均值：

| 真实 CFA | (0,0) | (0,1) | (1,0) | (1,1) |
| -------- | ----- | ----- | ----- | ----- |
| GRBG     | G     | R     | B     | G     |
| GBRG     | G     | B     | R     | G     |
| RGGB     | R     | G     | G     | B     |
| BGGR     | B     | G     | G     | R     |

### 新图实测（17.6 万平坦像素）

| 位置 (y%2,x%2) | 原始均值 | 推断   |
| -------------- | -------: | ------ |
| (0,0)          |  35261.0 | **G**  |
| (0,1)          |  24782.9 | R 或 B |
| (1,0)          |  21392.6 | R 或 B |
| (1,1)          |  35291.2 | **G**  |

判定：
- **(0,0)≈(1,1)**（差 0.08%）→ G 在主对角 → **真实 CFA ∈ {GRBG, GBRG}**（排除 RGGB/BGGR）；
- 区分 GRBG vs GBRG 依赖光源：`(0,1)=24783`、`(1,0)=21393`，
  暖光（R>B）→ GRBG；冷光（D65/荧光，B>R）→ GBRG；
- 光谱上看 G 最高、B 次之、R 最低更符合冷白/荧光灯灰阶场景，**倾向 GBRG**——但这是
  带光源假设的推断，最终以独立色卡对照为准。

---

## 7. 偏差统计方法讨论

### 7.1 三个指标各测什么（易混淆）

| 指标                      | 公式                                       | 测什么                                    | 用途           |
| ------------------------- | ------------------------------------------ | ----------------------------------------- | -------------- |
| mean 绝对差（有符号）     | `mean(项目 − Imatest)`                     | 软件**系统性偏高/偏低**多少、平均漂移多少 | 诊断方向       |
| mean 相对%（逐 ROI MAPE） | `mean(\|项目_i − Imatest_i\| / Imatest_i)` | 软件 vs 标准的**归一化**偏差              | **验收主判据** |
| MTF 绝对值                | Imatest 或项目测得的 MTF 值                | 模组/位置的**分辨能力**                   | 性能比较       |

> **常见误区**：相对% 度量的一直是"软件与标准的偏差"，**不是模组性能指标**。
> "模组 MTF 能力是否优秀"要看 **MTF 绝对值本身**：哪个 ROI/模组数值高、是否过规格阈值
> （PASS/FAIL）、模组间数值对比。哪怕软件偏差很小，模组 MTF 低依然说明性能差。

### 7.2 归一化与换算

- 绝对偏差有量纲；除以各自参考值 `Imatest_i` 得相对%（无量纲），**跨 ROI/跨模组可比**：
  同一绝对差对高 MTF 的 ROI 相对占比小、对低 MTF 的 ROI 相对占比大；
- 换算：`绝对偏差 = 相对% × Imatest 值`。MTF@0.125 常见 0.5~0.8 区间，
  2% 相对 ≈ 绝对差 **0.010~0.016**；老图 +0.0035/0.6718 ≈ 0.5%（整体均值口径，见 7.3）；
- 同量级示例：

| Imatest 参考 | 相对偏差 2% 对应的绝对差 |
| -----------: | -----------------------: |
|         0.80 |                    0.016 |
|         0.60 |                    0.012 |
|         0.50 |                    0.010 |

### 7.3 口径陷阱：整体均值相对差 vs 逐 ROI MAPE（重要）

| 口径                | 公式                                             | 特点                           |
| ------------------- | ------------------------------------------------ | ------------------------------ |
| 整体均值相对差      | `\|mean(项目) − mean(Imatest)\| / mean(Imatest)` | 正负偏差**相互抵消**，严重低估 |
| 逐 ROI MAPE（正确） | `mean(\|项目_i − Imatest_i\| / Imatest_i)`       | 逐点取绝对值，不抵消           |

实测对比（同一数据）：

| 图          | 整体均值相对差 | 逐 ROI MAPE |
| ----------- | -------------: | ----------: |
| 老图 OpenCV |          0.52% |   **0.99%** |
| 新图 GBRG   |          0.55% |   **1.71%** |

> **必须用逐 ROI MAPE 作为验收口径；整体均值相对差会因正负抵消严重低估，不得用于验收。**
> （本文早期"约 0.5% / 0.4%"即为此错误口径，已全部作废。）

### 7.4 验收线讨论（1% 是否太严？3% 是否可行？）

数据基础：
- 老图（ROI 与 Imatest 逐像素对齐）：MAPE **0.99%** → 1% 在"对齐良好"前提下**可达**；
- 新图（ROI 边界差 1 像素）：MAPE **1.71%** → 超线部分主要来自对齐噪声 + 个别 ROI。

结论：
- **平均 1% 偏严**：它把"ROI 对齐/测量噪声"也算进去了——对齐良好才可达，1 像素差异就能
  把它顶到 1.7%，实质在"测对齐"而非"测算法"；
- **平均 3% 偏松**：失去鉴别力——Bayer 选错的新图是 5.43%（3% 还能拦），但若某张图 Bayer
  错误影响只有 2~3% 会被漏放；软件 2~3% 的**系统性偏差**也会被当合格；生产 PASS/FAIL 可能
  把临界模组判反；
- **推荐（折中）**：
  ```
  主判据：平均逐 ROI MAPE ≤ 2%
  辅助判据：单点 max ≤ 3~4%
  ```
  老图 0.99%、新图 1.71% 均可过，不再被对齐噪声卡死；Bayer 选错（5.43%）与系统性偏差
  仍能被拦截，保留鉴别力；
- **前提**：定标前先做新图超线**归因**（ROI 对齐到像素级重算），确认超线来自对齐/噪声
  而非引擎或算法问题——若归因后确认是测量/对齐噪声，定 2% 合理；若发现引擎/算法问题，
  3% 反而会掩盖它。

### 7.5 推荐报告口径

```
ROI  Imatest  项目    绝对差   相对%
1    ...
...
mean  0.6688  0.6726  +0.0037  (整体均值差，仅诊断方向，非验收)
MAPE  —        —        —       1.71%   ← 验收主判据
max   ...                           ← 单点门槛
```

---

## 8. 结论汇总

1. **mtf_test.py 与主项目链路**：RAW → 双线性 demosaic → BT.709 luma → ROI → sfrmat5 C++
   引擎，与 Imatest 配置实质等价；
2. **去马赛克算法不是偏差来源**：OpenCV 双线性最贴合 Imatest（老图逐 ROI MAPE 0.99%），
   LibRaw 高级算法反而偏大很多（VNG 6.8% / AHD 11.9%）；但老图 0.99% 只是**临界压线**；
3. **Bayer 格式选错影响 Y-channel MTF 约 3~5%**；新图正确 CFA（GBRG）逐 ROI MAPE 1.71%
   仍**超 1% 验收线**，错误 CFA（GRBG）5.43%——G-only 完全免疫；
4. **「与 Imatest 吻合」不能判定真实 Bayer**（循环论证）；真实格式需独立证据，
   2×2 四角统计可将候选收敛到 {GRBG, GBRG}，最终以光源色温或色卡对照定夺；
5. **统计方法**：验收用逐 ROI MAPE（正负不抵消，加 max 单点门槛）；
   整体均值相对差会因正负抵消严重低估，**不得用于验收**；诊断用有符号绝对差。
   建议验收线：**平均 MAPE ≤ 2% + 单点 ≤ 3~4%**（1% 偏严、3% 偏松，见 §7.4）。

> **口径警示（重要）**：本文早期版本使用的"约 0.5% / 0.4%"是**整体均值相对差**
> `|mean(项目)−mean(Imatest)|/mean(Imatest)`，因正负偏差相互抵消而严重低估真实偏差，
> 已全部作废。所有验收口径一律采用**逐 ROI MAPE**（老图 OpenCV 0.99%、新图 GBRG 1.71%）。

---

## 9. 验证脚本与环境

| 脚本                            | 职责                                                                                 |
| ------------------------------- | ------------------------------------------------------------------------------------ |
| `reference/mtf_test_dcraw.py`   | 去马赛克算法对比（OpenCV vs LibRaw LINEAR/VNG/PPG/AHD）+ Imatest CSV 解析逐 ROI 对比 |
| `reference/bayer_swap_check.py` | GRBG vs GBRG 的 MTF 对比 + G 通道一致性 + 独立 2×2 四角统计                          |

环境与运行：

```powershell
# rawpy(LibRaw) 装在项目内 reference/dcraw_deps（--no-deps，防止 numpy 升级破坏 C++ 引擎）
conda env: LpIQtest312（numpy 1.26.4）
$env:PYTHONIOENCODING='utf-8'
& 'D:\ProgramData\Anaconda3\envs\LpIQtest312\python.exe' reference/mtf_test_dcraw.py
& 'D:\ProgramData\Anaconda3\envs\LpIQtest312\python.exe' reference/bayer_swap_check.py
```

测试图：
- 老图 `SN_0.65_D_07_30_2026_T_14_54_14.raw`（LF_fast 输出，1920×1200@10bit，真实 GRBG）；
- 新图 `SN_2_D_08_20_2026_T_10_43_03.raw`（assets/data/MTF/414012/2，1920×1200，真实候选 {GRBG, GBRG}，
  色卡对照倾向 GBRG）。
