# LeopardIQTest_Software

摄像头模组图像质量（Image Quality, IQ）评估软件，包含两部分：

- **`leopardiq/`** —— 算法库：MTF/SFR、Lens Shading（相对照度 / Color / LSC）、
  Flare（ISO 9358）、FOV（几何法 / 棋盘格法）等镜头质量指标的量化计算。
  核心 SFR 计算由 C++ 引擎 `leopardiq/mtf_sfrmat5_cpp.pyd`（ISO 12233 sfrmat5）完成。
- **`iqtest/`** —— GUI 应用（PySide6 + pyqtgraph）：向导式工作流
  （Select Images → Select Analysis → ANALYZE）、MTF ROI 框选、结果 Figure 展示、
  MTF 模组比较、Generalized Read Raw 全局设置。

## 目录结构

```
leopardiq/          # 算法库
  utils/            # raw_reader / image_io / image_preprocess / pass_fail / result_saver ...
  mtf/              # SFR/MTF：sfr_analyzer / mtf_calculator / centroid / cross_chart ...
  shading/          # 相对照度 / Color / LSC
  flare/            # ISO 9358 Flare
  fov/              # 视场角
iqtest/             # GUI 应用
  main.py           # 入口：python -m iqtest.main
  config/           # criteria JSON / LenFocus config / Read Raw 设置
  analysis/         # 算法适配器 + 模组比较纯逻辑
  panels/ figures/ widgets/
reference/          # 参考实现（遗留）
scripts/            # 截图辅助脚本
tests/              # 脚本式测试（python tests/test_*.py）
doc/                # 文档（规划 / 开发 / 优化方案）
```

## 环境安装

目标环境为 conda 环境 `LpIQtest312`（Python 3.12.13）。

```bash
conda create -n LpIQtest312 python=3.12
conda activate LpIQtest312
pip install -r requirements.txt
```

> ⚠️ `numpy` 必须锁定 1.x：`mtf_sfrmat5_cpp.pyd` 基于 NumPy 1.x ABI 编译，
> NumPy 2.x 下可能崩溃。`scipy` / `opencv-python` 需与 numpy 1.x 联动，勿单独升级。

## 运行

```bash
conda activate LpIQtest312
python -m iqtest.main
```

## 测试

测试为脚本式（非 pytest），在项目根目录、`LpIQtest312` 环境下运行。
Windows 控制台请先设置 UTF-8，避免 emoji/中文输出编码报错：

```bash
set PYTHONUTF8=1
python tests\test_phase1_1.py    # utils：图像 I/O / 黑电平 / Bayer / 滤波
python tests\test_phase2_1.py    # MTF/SFR：质心 / 标板几何 / ROI / 评估
python tests\test_phase2_2.py    # Shading
python tests\test_phase2_4.py    # Flare
python tests\test_phase2_5.py    # FOV
python tests\test_m3_*.py        # MTF 算法（Gamma / MTF 指标 / 引擎 / 导出）
```

`tests/test_m4_*.py` 为 GUI 相关测试，需要图形环境。

## 更多文档

- `doc/LeopardIQ-IQ测试软件规划.md` —— 软件整体规划
- `doc/LeopardIQ-IQ测试软件-MTF开发.md` —— MTF 开发细节
- `doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md` —— MTF 模组比较
- `doc/代码优化方案.md` —— 代码清理与后续重构路线图
