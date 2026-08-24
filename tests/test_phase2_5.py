"""
Phase 2.5 验证测试：FOV 模块。

测试内容：
[1/4] 模块导入
[2/4] 几何法（compute_fov_from_geometry / FOVCalculator.from_geometry）
[3/4] 棋盘格法（合成棋盘格 → detect corners → FOV）
[4/4] Imatest 解析（parse_imatest_fov / evaluate_imatest_fov）

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_phase2_5.py
"""

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


BOARD_SIZE = (7, 5)      # 内角点 (cols, rows)
GRID_PX = 40             # 每格像素
GRID_MM = 80.0           # 每格物理尺寸 mm
DIST_MM = 544.0          # 拍摄距离 mm


def make_chessboard():
    """合成棋盘格图像：白边 + 黑白相间方格。"""
    cols, rows = BOARD_SIZE[0] + 1, BOARD_SIZE[1] + 1  # 方格数
    margin = 40
    h = rows * GRID_PX + 2 * margin
    w = cols * GRID_PX + 2 * margin
    img = np.full((h, w), 255, dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                y0 = margin + r * GRID_PX
                x0 = margin + c * GRID_PX
                img[y0:y0 + GRID_PX, x0:x0 + GRID_PX] = 0
    return img


def test_imports():
    print("[1/4] 模块导入")
    from leopardiq.fov import (  # noqa: F401
        FOVCalculator,
        analyze_fov,
        angle_of_triangle,
        compute_fov_from_chessboard,
        compute_fov_from_geometry,
        detect_chessboard_corners,
        evaluate_imatest_fov,
        parse_imatest_fov,
    )

    check("leopardiq.fov 全部导入成功", True)


def test_geometry():
    print("[2/4] 几何法")
    from leopardiq.fov import FOVCalculator, analyze_fov, compute_fov_from_geometry

    h = [19, 252]
    v = [380.5, 479]
    f = 67.8
    result = compute_fov_from_geometry(h, v, f)
    # 手算：h_dist=(252-19)/2=116.5, HFOV=2*atan(116.5/67.8)
    expected_h = 2 * np.rad2deg(np.arctan(116.5 / 67.8))
    expected_v = 2 * np.rad2deg(np.arctan((479 - 380.5) / 2 / 67.8))
    check("HFOV 公式正确", abs(result["hfov"] - expected_h) < 1e-9,
          f"{result['hfov']:.2f}°")
    check("VFOV 公式正确", abs(result["vfov"] - expected_v) < 1e-9,
          f"{result['vfov']:.2f}°")
    check("DFOV = norm(HFOV, VFOV)",
          abs(result["dfov"] - np.linalg.norm([expected_h, expected_v])) < 1e-9)

    # criteria 判定 + 标准接口
    calc = FOVCalculator(criteria={"hfov": [50, 60], "vfov": [50, 60]})
    std = calc.from_geometry(h, v, f)
    check("HFOV 超范围判定 FAIL", not std["pass"])

    std2 = analyze_fov(None, {
        "method": "geometry", "h_range": h, "v_range": v, "focal_distance": f,
        "criteria": {"hfov": [100, 130], "vfov": [60, 80], "dfov": [120, 150]},
    })
    check("标准接口范围内判定 PASS", std2["pass"],
          str({k: v["status"] for k, v in std2["metrics"].items()}))


def test_chessboard():
    print("[3/4] 棋盘格法")
    from leopardiq.fov import (
        FOVCalculator,
        compute_fov_from_chessboard,
        detect_chessboard_corners,
    )

    img = make_chessboard()
    corners = detect_chessboard_corners(img, BOARD_SIZE)
    check("角点形状 (rows, cols, 2)",
          corners.shape == (BOARD_SIZE[1], BOARD_SIZE[0], 2))
    # 相邻角点距离应接近 GRID_PX
    dists = np.linalg.norm(corners[:, 0:-1] - corners[:, 1:], axis=-1)
    check("角点间距 ≈ 40px", abs(np.mean(dists) - GRID_PX) < 1.0,
          f"{np.mean(dists):.2f}")

    result = compute_fov_from_chessboard(img, GRID_MM, BOARD_SIZE, DIST_MM)
    h, w = img.shape[:2]
    # 期望：pixel→mm = 80/40 = 2.0，w_size = w*2 = 680mm（合成图 w=360）
    expected_w_mm = w * (GRID_MM / GRID_PX)
    check("视场宽度 ≈ 图像宽×2mm",
          abs(result["width_mm"] - expected_w_mm) / expected_w_mm < 0.05,
          f"{result['width_mm']:.1f} vs {expected_w_mm:.1f}")
    expected_hfov = 2 * np.rad2deg(np.arctan(expected_w_mm * 0.5 / DIST_MM))
    check("HFOV 与手算一致",
          abs(result["hfov"] - expected_hfov) < 2.0,
          f"{result['hfov']:.2f}° vs {expected_hfov:.2f}°")
    check("DFOV > HFOV > VFOV", result["dfov"] > result["hfov"] > result["vfov"])

    calc = FOVCalculator(criteria={"hfov": [0, 180]})
    std = calc.from_chessboard(img, GRID_MM, BOARD_SIZE, DIST_MM)
    check("FOVCalculator 棋盘格法 PASS", std["pass"])
    check("details 含比例图", "ratios_x" in std["details"])


def test_imatest():
    print("[4/4] Imatest 解析")
    from leopardiq.fov import evaluate_imatest_fov, parse_imatest_fov

    fake = {
        "checkerboardResults": {
            "FieldofView_DiagHV_degrees": [70.5, 55.2, 45.8],
            "x_distortion_decenter": [14.0],
            "y_distortion_decenter": [14.0],
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as fp:
        json.dump(fake, fp)
        tmp_path = fp.name

    data = parse_imatest_fov(tmp_path)
    check("FOV 解析正确",
          data["dfov"] == 70.5 and data["hfov"] == 55.2 and data["vfov"] == 45.8)
    check("oc_shift = sqrt(14²+14²)",
          abs(data["oc_shift"] - np.sqrt(14 ** 2 + 14 ** 2)) < 1e-9)

    result = evaluate_imatest_fov(
        tmp_path,
        hfov_criteria=(54, 57),
        vfov_criteria=(44, 47),
        dfov_criteria=(68, 72),
        angular_res=28,
        oc_shift_criteria=1.0,
    )
    check("Imatest 评估整体 PASS", result["pass"],
          str({k: v["status"] for k, v in result["metrics"].items()}))
    check("ang_oc_shift ≈ 0.707°",
          abs(result["metrics"]["ang_oc_shift"]["value"] - 19.799 / 28) < 0.01)

    result_fail = evaluate_imatest_fov(
        tmp_path, (54, 55), (44, 47), (68, 72), 28, 1.0
    )
    check("HFOV 55.2 超出 [54,55] 判定 FAIL", not result_fail["pass"])

    Path(tmp_path).unlink()


def main():
    print("=" * 60)
    print("Phase 2.5 验证测试：FOV 模块")
    print("=" * 60)

    test_imports()
    test_geometry()
    test_chessboard()
    test_imatest()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
