"""
M3.4 验证测试：MTF/SFR Gamma (input) 线性化参数（仿 Imatest「Input gamma value」）。

依据 Imatest 官方文档（imatest.com/docs/sfr_instructions2）：
- 输入 Gamma 为编码（前向）Gamma，线性化取其倒数：pixel^(1/gamma)；
- 线性 RAW 数据 gamma=1.0（等价于不线性化，项目默认）；
- BMP/JPEG 等 sRGB 编码图像 gamma≈0.45~0.5（Imatest 默认 0.5）；
- Gamma 超出 [0.3, 0.8]（除 1.0 外）视为异常选择，分析时给出警告。

测试内容：
[1/4] linearize_gamma 单元行为
[2/4] Gamma 往返：编码图 + gamma=0.5 线性化 ≈ 线性图直接计算
[3/4] 适配器端到端：gamma=1.0 默认兼容 / gamma=0.5 还原编码图 / 非法配置报错
[4/4] 面板 schema：默认值与 config 往返

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m3_4.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path

# 测试与用户保存的 Read Raw 全局设置隔离（~/.leopardiqlts），保证结果可复现
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from test_m3_1 import OUT_DIR, make_chart, make_mono_chart_file, top_edge_rois  # noqa: E402

PASS_COUNT = 0
FAIL_COUNT = 0

#: 测试用编码 Gamma（sRGB 近似 1/2.2 的惯用值，Imatest 默认 0.5）
GAMMA_ENC = 0.5


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def _run(config, path):
    from iqtest.analysis.mtf_adapter import analyze_mtf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_mtf([path], config)


def _roi_patch(image: np.ndarray, rect) -> np.ndarray:
    x, y, w, h = [int(v) for v in rect]
    return image[y:y + h, x:x + w]


def make_gamma_chart_file(gamma: float = GAMMA_ENC) -> Path:
    """将线性合成标板按编码 Gamma 变换后存为 PNG（模拟 sRGB/BMP 输入）。"""
    path = OUT_DIR / f"sfr_chart_gamma{gamma:g}.png"
    img = np.squeeze(make_chart())  # 线性灰度 0~255
    encoded = 255.0 * (np.clip(img, 0, 255) / 255.0) ** gamma
    cv2.imwrite(str(path), np.clip(encoded, 0, 255).astype(np.uint8))
    return path


# ----------------------------------------------------------------------
# [1/4] linearize_gamma 单元行为
# ----------------------------------------------------------------------
def test_gamma_units():
    print("[1/4] linearize_gamma 单元行为")
    from leopardiq.mtf import linearize_gamma

    patch = np.array([[0.0, 20.0], [220.0, 100.0]])

    # gamma = 1.0 → 原样返回（Imatest：输入 Gamma=1 等价于不线性化）
    out1 = linearize_gamma(patch, 1.0)
    check("gamma=1.0 原样返回", np.array_equal(out1, patch.astype(np.float64)))

    # gamma = 0.5 → 平方（线性化取倒数 1/0.5 = 2）
    out2 = linearize_gamma(patch, 0.5)
    check("gamma=0.5 → pixel^2",
          np.allclose(out2, patch.astype(np.float64) ** 2))

    # 负值截断为 0（黑电平校正残差保护）
    out3 = linearize_gamma(np.array([[-5.0, 4.0]]), 0.5)
    check("负值截断为 0", out3[0, 0] == 0.0 and out3[0, 1] == 16.0)

    # gamma ≤ 0 → 明确报错
    try:
        linearize_gamma(patch, 0.0)
    except ValueError as e:
        check("gamma=0 → ValueError", "正数" in str(e), str(e)[:24])
    else:
        check("gamma=0 → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [2/4] Gamma 往返一致性
# ----------------------------------------------------------------------
def test_gamma_roundtrip():
    print("[2/4] Gamma 往返：编码图线性化 ≈ 线性图直接计算")
    from leopardiq.mtf import compute_mtf_array, compute_mtf_metrics

    linear = np.squeeze(make_chart())
    encoded = 255.0 * (np.clip(linear, 0, 255) / 255.0) ** GAMMA_ENC
    rect = top_edge_rois()[0]
    patch_lin = _roi_patch(linear, rect)
    patch_enc = _roi_patch(encoded, rect)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mtf_lin = compute_mtf_array(patch_lin)
        mtf_enc_raw = compute_mtf_array(patch_enc)              # 不线性化
        mtf_enc_fix = compute_mtf_array(patch_enc, gamma=GAMMA_ENC)  # 线性化

    check("线性图 MTF 计算有效", mtf_lin is not None)
    check("编码图 MTF 计算有效",
          mtf_enc_raw is not None and mtf_enc_fix is not None)
    if mtf_lin is None or mtf_enc_raw is None or mtf_enc_fix is None:
        return

    mtf50_lin = compute_mtf_metrics(mtf_lin, ("mtf50",))["mtf50"]
    mtf50_raw = compute_mtf_metrics(mtf_enc_raw, ("mtf50",))["mtf50"]
    mtf50_fix = compute_mtf_metrics(mtf_enc_fix, ("mtf50",))["mtf50"]

    # 线性化后应与线性图结果几乎一致（浮点幂往返，无量化）
    check("编码图 + gamma 线性化 ≈ 线性图 MTF50",
          abs(mtf50_fix - mtf50_lin) < 0.01,
          f"fix={mtf50_fix:.4f} vs lin={mtf50_lin:.4f}")
    # 不线性化存在 Gamma 失真误差；线性化应显著更接近线性参考
    # （Imatest：gamma 小误差对 MTF 影响较小，故不断言固定差值幅度）
    check("线性化后比不线性化更接近线性参考",
          abs(mtf50_fix - mtf50_lin) < abs(mtf50_raw - mtf50_lin),
          f"fix diff={abs(mtf50_fix - mtf50_lin):.4f} < "
          f"raw diff={abs(mtf50_raw - mtf50_lin):.4f}")

    # compute_roi_sfr 同口径：gamma=0.5 线性化 ≈ 线性参考
    from leopardiq.mtf import compute_roi_sfr

    frequency = np.array([0.125])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r_lin = np.full((1, 1, 1), np.nan)
        compute_roi_sfr(patch_lin[:, :, np.newaxis], frequency, 1, 0, r_lin)
        r_fix = np.full((1, 1, 1), np.nan)
        v_fix = compute_roi_sfr(
            patch_enc[:, :, np.newaxis], frequency, 1, 0, r_fix, gamma=GAMMA_ENC
        )
        r_raw = np.full((1, 1, 1), np.nan)
        compute_roi_sfr(patch_enc[:, :, np.newaxis], frequency, 1, 0, r_raw)
    check("compute_roi_sfr gamma 口径有效", v_fix)
    check("SFR@0.125：线性化 ≈ 线性参考",
          abs(r_fix[0, 0, 0] - r_lin[0, 0, 0]) < 0.01,
          f"fix={r_fix[0, 0, 0]:.4f} vs lin={r_lin[0, 0, 0]:.4f}")
    check("SFR@0.125：线性化比不线性化更接近参考",
          abs(r_fix[0, 0, 0] - r_lin[0, 0, 0])
          < abs(r_raw[0, 0, 0] - r_lin[0, 0, 0]))


# ----------------------------------------------------------------------
# [3/4] 适配器端到端
# ----------------------------------------------------------------------
def test_adapter_gamma():
    print("[3/4] 适配器：gamma=1.0 默认兼容 / gamma=0.5 还原 / 非法配置")
    path_lin = make_mono_chart_file()
    path_enc = make_gamma_chart_file()
    rois_lin = [{"image": path_lin.name, "rect": top_edge_rois()[0]}]
    rois_enc = [{"image": path_enc.name, "rect": top_edge_rois()[0]}]

    def cfg(rois, **params):
        p = {"cfa": "Y", "freq1": 0.125, "rois": rois}
        p.update(params)
        return {"params": p, "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0}}

    # 旧配置（无 gamma 键）→ gamma=1.0 不线性化，结果与历史一致
    base = _run(cfg(rois_lin), path_lin)
    check("旧配置默认 gamma=1.0",
          base["details"]["gamma"] == 1.0
          and base["details"]["curves"][0]["gamma"] == 1.0)
    mtf50_lin = base["metrics"]["ROI1_readout1"]["value"][0]
    check("线性图默认分析有效", 0 < mtf50_lin < 0.6, f"{mtf50_lin:.4f}")

    # 显式 gamma=1.0 与旧配置结果一致
    r_g1 = _run(cfg(rois_lin, gamma=1.0), path_lin)
    check("显式 gamma=1.0 == 旧配置",
          r_g1["metrics"]["ROI1_readout1"]["value"][0] == mtf50_lin)

    # 旧版配置残留的 linearization/chart_contrast 键被忽略，不影响结果
    r_legacy = _run(cfg(rois_lin, linearization="No linearization",
                        chart_contrast=4.0), path_lin)
    check("旧版 linearization/chart_contrast 键被忽略",
          r_legacy["metrics"]["ROI1_readout1"]["value"][0] == mtf50_lin)

    # 编码图 + gamma=0.5 → 还原后 ≈ 线性图结果
    r_in = _run(cfg(rois_enc, gamma=GAMMA_ENC), path_enc)
    mtf50_in = r_in["metrics"]["ROI1_readout1"]["value"][0]
    check("gamma 记录进 details / curves / roi_records",
          r_in["details"]["gamma"] == GAMMA_ENC
          and r_in["details"]["curves"][0]["gamma"] == GAMMA_ENC
          and r_in["details"]["rois"][0]["gamma"] == GAMMA_ENC)
    check("编码图 + gamma=0.5 ≈ 线性图 Readout1（8bit 量化容差）",
          abs(mtf50_in - mtf50_lin) < 0.03,
          f"in={mtf50_in:.4f} vs lin={mtf50_lin:.4f}")

    # 判定逻辑不受 Gamma 配置影响（PASS/FAIL 结构保持）
    check("判定键结构保持",
          r_in["metrics"]["ROI1_readout1"]["status"] in ("PASS", "FAIL")
          and r_in["metrics"]["ROI1_mtf@0.125"]["status"] in ("PASS", "FAIL"))

    # 非法配置 → 明确报错
    for bad_params, kw in (
        ({"gamma": 0.05}, "0.1~2.0"),
        ({"gamma": 3.0}, "0.1~2.0"),
    ):
        try:
            _run(cfg(rois_lin, **bad_params), path_lin)
        except ValueError as e:
            check(f"{bad_params} → ValueError", kw in str(e), str(e)[:36])
        else:
            check(f"{bad_params} → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [4/4] 面板 schema
# ----------------------------------------------------------------------
def test_panel_schema():
    print("[4/4] 面板 schema：Gamma 默认值与 config 往返")
    from PySide6.QtWidgets import QApplication

    from iqtest.panels.mtf_panel import MtfPanel

    app = QApplication.instance() or QApplication([])
    del app

    defaults = MtfPanel.default_config()
    check("默认 params 含 gamma 键", "gamma" in defaults["params"])
    check("默认 gamma=1.0", defaults["params"]["gamma"] == 1.0)
    check("默认 params 不含 linearization/chart_contrast",
          "linearization" not in defaults["params"]
          and "chart_contrast" not in defaults["params"])

    panel = MtfPanel(session=None)
    panel.params_form.set_values({"gamma": 0.5})
    cfg = panel.config()
    check("config 存储 gamma=0.5", cfg["params"]["gamma"] == 0.5)

    panel2 = MtfPanel(session=None)
    panel2.set_config(cfg)
    check("set_config 往返一致", panel2.params_form.values()["gamma"] == 0.5)

    # 旧版配置含 linearization/chart_contrast：set_config 忽略未知键不报错
    panel3 = MtfPanel(session=None)
    legacy = panel3.config()
    legacy["params"].update(
        {"linearization": "No linearization", "chart_contrast": 4.0,
         "gamma": 0.46}
    )
    panel3.set_config(legacy)
    check("旧版配置兼容（未知键忽略，gamma 生效）",
          panel3.params_form.values()["gamma"] == 0.46)


def main():
    print("=" * 60)
    print("M3.4 验证测试：Gamma (input) 线性化参数")
    print("=" * 60)

    test_gamma_units()
    test_gamma_roundtrip()
    test_adapter_gamma()
    test_panel_schema()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
