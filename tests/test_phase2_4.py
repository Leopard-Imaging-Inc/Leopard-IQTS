"""
Phase 2.4 验证测试：Flare 模块（ISO 9358 Type A/B/C）。

测试内容：
[1/4] 模块导入
[2/4] 圆斑检测与区域 luma（detect_flare_circles / compute_region_luma）
[3/4] Type C 分析（FlareAnalyzer.analyze_type_c / analyze_flare）
[4/4] Type A / B 分析与判定

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_phase2_4.py
"""

import sys
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


WHITE = 225.0
BLACK_VALUE = 2.25   # 黑斑亮度（模拟 1% flare）


def make_flare_chart(black_value=BLACK_VALUE, white=WHITE):
    """合成 flare 标板：白底 + 3 个黑斑圆（半径 30）。"""
    img = np.full((800, 800), white, dtype=np.float64)
    for (cx, cy) in [(200, 200), (400, 400), (600, 600)]:
        cv2.circle(img, (cx, cy), 30, black_value, -1)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    return img.astype(np.uint8)


def test_imports():
    print("[1/4] 模块导入")
    from leopardiq.flare import (  # noqa: F401
        FlareAnalyzer,
        analyze_flare,
        compute_d70,
        compute_region_luma,
        detect_flare_circles,
        render_debug_overlay,
    )

    check("leopardiq.flare 全部导入成功", True)


def test_detection_and_luma():
    print("[2/4] 圆斑检测与区域 luma")
    from leopardiq.flare import (
        REGION_BLACK,
        REGION_WHITE_RIGHT,
        compute_region_luma,
        detect_flare_circles,
        render_debug_overlay,
    )

    img = make_flare_chart()
    circles = detect_flare_circles(img)
    check("检测到 3 个圆斑", circles is not None and len(circles) == 3,
          f"got {None if circles is None else len(circles)}")

    d70 = 800 * np.sqrt(2) / 70
    y_black = compute_region_luma(img, circles, d70, REGION_BLACK)
    check("黑斑 luma ≈ 2.25",
          all(abs(v - BLACK_VALUE) < 1.0 for v in y_black),
          f"{[f'{v:.2f}' for v in y_black]}")

    y_white = compute_region_luma(img, circles, d70, REGION_WHITE_RIGHT)
    check("白色参考区 luma ≈ 225",
          all(v > 200 for v in y_white),
          f"{[f'{v:.1f}' for v in y_white]}")

    overlay = render_debug_overlay(img, circles, d70)
    check("调试叠加图返回 BGR 图像",
          overlay.ndim == 3 and overlay.shape[:2] == img.shape[:2])

    # 无圆斑图像
    blank = np.full((800, 800), 200, dtype=np.uint8)
    check("无圆斑返回 None", detect_flare_circles(blank) is None)


def test_type_c():
    print("[3/4] Type C 分析")
    from leopardiq.flare import FlareAnalyzer, analyze_flare

    img = make_flare_chart()
    analyzer = FlareAnalyzer()
    result = analyzer.analyze_type_c(img, debug=True)
    expected = BLACK_VALUE / WHITE * 100  # ≈ 1.0%
    check("Type C flare ≈ 1%", abs(result["metrics"]["flare"]["value"] - expected) < 0.3,
          f"{result['metrics']['flare']['value']:.3f}%")
    check("无 criteria 默认 PASS", result["pass"])
    check("debug 返回可视化", "visualization" in result)
    check("details 含 3 个圆斑数据",
          len(result["details"]["flare_per_circle"]) == 3)

    # criteria 判定
    result_fail = analyzer.analyze_type_c(img, criteria=0.5)
    check("criteria=0.5 判定 FAIL", not result_fail["pass"])

    # 标准接口
    std = analyze_flare(img, {"method": "C", "criteria": 2.0})
    check("analyze_flare 标准接口 PASS", std["pass"])


def test_type_a_b():
    print("[4/4] Type A / B 分析")
    from leopardiq.flare import FlareAnalyzer

    analyzer = FlareAnalyzer()
    img_h1_chart1 = make_flare_chart(black_value=BLACK_VALUE, white=WHITE)
    img_h2_chart2 = make_flare_chart(black_value=2.0, white=WHITE)
    img_h2_chart1 = make_flare_chart(black_value=BLACK_VALUE * 8, white=WHITE)

    # 注意：uint8 量化后 YB1 = 2（2.25→2），YB2 = 2，YB3 = 18
    # Type B: F = ((YB1/H1) - (YB2/H2)) / (YW1/H1) * 100
    result_b = analyzer.analyze_type_b(img_h1_chart1, img_h2_chart2, h1=1.0, h2=8.0)
    expected_b = (2 - 2 / 8) / WHITE * 100
    check("Type B flare 公式正确",
          abs(result_b["metrics"]["flare"]["value"] - expected_b) < 0.1,
          f"{result_b['metrics']['flare']['value']:.3f}% vs {expected_b:.3f}%")

    # Type A: F = ((YB3/H2) - (YB2/H2)) / (YW1/H1) * 100
    result_a = analyzer.analyze_type_a(
        img_h1_chart1, img_h2_chart2, img_h2_chart1, h1=1.0, h2=8.0
    )
    expected_a = (18 / 8 - 2 / 8) / WHITE * 100
    check("Type A flare 公式正确",
          abs(result_a["metrics"]["flare"]["value"] - expected_a) < 0.1,
          f"{result_a['metrics']['flare']['value']:.3f}% vs {expected_a:.3f}%")

    check("Type A method 标记正确",
          result_a["details"]["method"] == "ISO 9358 Type A")


def main():
    print("=" * 60)
    print("Phase 2.4 验证测试：Flare 模块")
    print("=" * 60)

    test_imports()
    test_detection_and_luma()
    test_type_c()
    test_type_a_b()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
