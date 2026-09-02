# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['F:/project/python/LeopardIQTest_Software/iqtest/main.py'],
    pathex=[],
    binaries=[],
    datas=[('F:/project/python/LeopardIQTest_Software/assets/leopard-logo.jpg', 'assets'), ('F:/project/python/LeopardIQTest_Software/leopardiq/mtf_sfrmat5_cpp.pyd', 'leopardiq'), ('F:/project/python/LeopardIQTest_Software/iqtest/config/default_criteria.json', 'iqtest/config'), ('F:/project/python/LeopardIQTest_Software/assets/config/MTF/config-AR0234.json', 'assets/config/MTF'), ('F:/project/python/LeopardIQTest_Software/assets/config/read_raw_settings.json', 'assets/config')],
    hiddenimports=['iqtest.analysis', 'iqtest.analysis.mtf_adapter', 'iqtest.analysis.mtf_compare', 'iqtest.analysis.mtf_compare._core', 'iqtest.analysis.mtf_compare._csv_io', 'iqtest.analysis.mtf_compare._model', 'iqtest.analysis.mtf_export', 'iqtest.analysis.shading_adapter', 'iqtest.analysis.shading_export', 'iqtest.figures.base_figure', 'iqtest.figures.mtf_figure', 'iqtest.figures.shading_figure', 'iqtest.panels.analysis_options', 'iqtest.panels.base_panel', 'iqtest.panels.color_panel', 'iqtest.panels.flare_panel', 'iqtest.panels.fov_panel', 'iqtest.panels.mtf_compare_charts', 'iqtest.panels.mtf_compare_panel', 'iqtest.panels.mtf_panel', 'iqtest.panels.shading_panel', 'iqtest.widgets.config_form', 'iqtest.widgets.free_stack', 'iqtest.widgets.image_view', 'iqtest.widgets.read_raw_dialog', 'iqtest.widgets.roi_dialog', 'iqtest.widgets.source_images', 'iqtest.config.lf_config', 'iqtest.config.lf_csv', 'iqtest.config.read_raw_settings', 'iqtest.config.store', 'iqtest.main_window', 'iqtest.runner', 'iqtest.session', 'iqtest.style', 'leopardiq.mtf', 'leopardiq.mtf.assessment', 'leopardiq.mtf.centroid', 'leopardiq.mtf.cross_chart', 'leopardiq.mtf.mtf_calculator', 'leopardiq.mtf.peak_focus', 'leopardiq.mtf.sfr_analyzer', 'leopardiq.mtf.square_chart', 'leopardiq.mtf.units', 'leopardiq.flare', 'leopardiq.flare.flare_analyzer', 'leopardiq.flare.flare_regions', 'leopardiq.fov', 'leopardiq.fov.fov_calculator', 'leopardiq.fov.fov_from_chessboard', 'leopardiq.fov.imatest', 'leopardiq.shading', 'leopardiq.shading.color_uniformity', 'leopardiq.shading.lsc', 'leopardiq.shading.relative_illumination', 'leopardiq.shading.shading_profile', 'leopardiq.utils', 'leopardiq.utils.binning', 'leopardiq.utils.common', 'leopardiq.utils.image_io', 'leopardiq.utils.image_preprocess', 'leopardiq.utils.pass_fail', 'leopardiq.utils.raw_reader', 'leopardiq.utils.result_saver', 'cv2', 'scipy', 'scipy.ndimage', 'scipy.interpolate', 'scipy.signal', 'scipy.optimize', 'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends.backend_qtagg', 'yaml', 'pyqtgraph', 'PIL', 'PIL.Image', 'numpy'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'pytest', 'pdb', 'idlelib', 'lib2to3'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LeopardIQTS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['F:/project/python/LeopardIQTest_Software/assets/leopard-logo.jpg'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LeopardIQTS',
)
