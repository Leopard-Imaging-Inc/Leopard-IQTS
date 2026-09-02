"""
PyInstaller 打包脚本 — LeopardIQTS

用法（在项目根目录执行）：
    python build.py

输出：dist/LeopardIQTS/ 目录（含 LeopardIQTS.exe 及全部依赖）
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def build() -> None:
    import PyInstaller.__main__

    # 数据文件参数：--add-data "src;dest" (Windows 用 ; 分隔)
    datas = [
        f"{ROOT / 'assets' / 'leopard-logo.jpg'};assets",
        f"{ROOT / 'leopardiq' / 'mtf_sfrmat5_cpp.pyd'};leopardiq",
        f"{ROOT / 'iqtest' / 'config' / 'default_criteria.json'};iqtest/config",
        f"{ROOT / 'assets' / 'config' / 'MTF' / 'config-AR0234.json'};assets/config/MTF",
        f"{ROOT / 'assets' / 'config' / 'read_raw_settings.json'};assets/config",
    ]

    # 隐藏导入
    hiddenimports = [
        "iqtest.analysis",
        "iqtest.analysis.mtf_adapter",
        "iqtest.analysis.mtf_compare",
        "iqtest.analysis.mtf_compare._core",
        "iqtest.analysis.mtf_compare._csv_io",
        "iqtest.analysis.mtf_compare._model",
        "iqtest.analysis.mtf_export",
        "iqtest.analysis.shading_adapter",
        "iqtest.analysis.shading_export",
        "iqtest.figures.base_figure",
        "iqtest.figures.mtf_figure",
        "iqtest.figures.shading_figure",
        "iqtest.panels.analysis_options",
        "iqtest.panels.base_panel",
        "iqtest.panels.color_panel",
        "iqtest.panels.flare_panel",
        "iqtest.panels.fov_panel",
        "iqtest.panels.mtf_compare_charts",
        "iqtest.panels.mtf_compare_panel",
        "iqtest.panels.mtf_panel",
        "iqtest.panels.shading_panel",
        "iqtest.widgets.config_form",
        "iqtest.widgets.free_stack",
        "iqtest.widgets.image_view",
        "iqtest.widgets.read_raw_dialog",
        "iqtest.widgets.roi_dialog",
        "iqtest.widgets.source_images",
        "iqtest.config.lf_config",
        "iqtest.config.lf_csv",
        "iqtest.config.read_raw_settings",
        "iqtest.config.store",
        "iqtest.main_window",
        "iqtest.runner",
        "iqtest.session",
        "iqtest.style",
        "leopardiq.mtf",
        "leopardiq.mtf.assessment",
        "leopardiq.mtf.centroid",
        "leopardiq.mtf.cross_chart",
        "leopardiq.mtf.mtf_calculator",
        "leopardiq.mtf.peak_focus",
        "leopardiq.mtf.sfr_analyzer",
        "leopardiq.mtf.square_chart",
        "leopardiq.mtf.units",
        "leopardiq.flare",
        "leopardiq.flare.flare_analyzer",
        "leopardiq.flare.flare_regions",
        "leopardiq.fov",
        "leopardiq.fov.fov_calculator",
        "leopardiq.fov.fov_from_chessboard",
        "leopardiq.fov.imatest",
        "leopardiq.shading",
        "leopardiq.shading.color_uniformity",
        "leopardiq.shading.lsc",
        "leopardiq.shading.relative_illumination",
        "leopardiq.shading.shading_profile",
        "leopardiq.utils",
        "leopardiq.utils.binning",
        "leopardiq.utils.common",
        "leopardiq.utils.image_io",
        "leopardiq.utils.image_preprocess",
        "leopardiq.utils.pass_fail",
        "leopardiq.utils.raw_reader",
        "leopardiq.utils.result_saver",
        "cv2",
        "scipy",
        "scipy.ndimage",
        "scipy.interpolate",
        "scipy.signal",
        "scipy.optimize",
        "matplotlib",
        "matplotlib.pyplot",
        "matplotlib.backends.backend_qtagg",
        "yaml",
        "pyqtgraph",
        "PIL",
        "PIL.Image",
        "numpy",
    ]

    # 排除项 — 注意：pydoc/doctest 不能排除，scipy 内部依赖它们
    excludes = [
        "tkinter",
        "unittest",
        "test",
        "pytest",
        "pdb",
        "idlelib",
        "lib2to3",
    ]

    args = [
        str(ROOT / "iqtest" / "main.py"),
        "--name=LeopardIQTS",
        "--onedir",                 # 单目录模式（启动快，体积合理）
        "--windowed",               # GUI 模式，不显示控制台
        "--noconfirm",              # 覆盖已有输出目录
        "--clean",                  # 清理临时文件
    ]

    # 图标
    icon_path = ROOT / "assets" / "leopard-logo.jpg"
    if icon_path.exists():
        args.append(f"--icon={icon_path}")

    # 数据文件
    for d in datas:
        args.append(f"--add-data={d}")

    # 隐藏导入
    for hi in hiddenimports:
        args.append(f"--hidden-import={hi}")

    # 排除项
    for ex in excludes:
        args.append(f"--exclude-module={ex}")

    # 工作目录
    args.append(f"--workpath={ROOT / 'build'}")
    args.append(f"--distpath={ROOT / 'dist'}")
    args.append(f"--specpath={ROOT}")

    print("=" * 60)
    print("PyInstaller 打包参数：")
    for arg in args:
        print(f"  {arg}")
    print("=" * 60)
    print()

    PyInstaller.__main__.run(args)

    print()
    print("=" * 60)
    print("✅ 打包完成！")
    print(f"   输出目录：{ROOT / 'dist' / 'LeopardIQTS'}")
    print(f"   可执行文件：{ROOT / 'dist' / 'LeopardIQTS' / 'LeopardIQTS.exe'}")
    print("=" * 60)


if __name__ == "__main__":
    build()
