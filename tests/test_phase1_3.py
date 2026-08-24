"""Phase 1.3 验证测试：下采样与通用工具。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leopardiq.utils import (
    bin_image,
    create_disk_structuring_element,
    extract_largest_region,
    filter_centroid,
    round_half_up,
)

passed, failed = 0, 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name} {detail}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


print("[1/5] bin_image 下采样")
img = np.arange(64, dtype=float).reshape(8, 8)
binned = bin_image(img, 2, 2)
check("2D shape", binned.shape == (4, 4), f"shape={binned.shape}")
# 块均值校验：原 Fortran 序分块，第一个 block 含 img[:, :2] 前两列
expected_first = img[:2, :2].reshape(2, 1, 2, 1, order="F").mean()
check("2D mean value", np.isclose(binned[0, 0], expected_first), f"{binned[0,0]:.2f} vs {expected_first:.2f}")

img3 = np.stack([img, img * 2], axis=-1)
binned3 = bin_image(img3, 2, 2)
check("3D shape", binned3.shape == (4, 4, 2))
check("3D channel ratio", np.isclose(binned3[0, 0, 1] / binned3[0, 0, 0], 2.0))

odd = np.arange(77, dtype=float).reshape(11, 7)
binned_odd = bin_image(odd, 2, 2)
check("odd dims no crash", binned_odd.shape == (5, 3), f"shape={binned_odd.shape}")

print("[2/5] create_disk_structuring_element")
disk = create_disk_structuring_element(10)
check("shape", disk.shape == (19, 19))
check("corners zero", disk[0, 0] == 0 and disk[-1, -1] == 0)
check("center one", disk[9, 9] == 1)

print("[3/5] extract_largest_region")
mask = np.zeros((20, 20), dtype=np.uint8)
mask[2:5, 2:5] = 1      # 小区域
mask[10:18, 10:18] = 1  # 大区域
out = extract_largest_region(mask)
check("largest kept", out.sum() == 64 and out[12, 12] == 1 and out[3, 3] == 0)

print("[4/5] round_half_up")
check("2.5 -> 3", round_half_up(2.5) == 3)
check("1.5 -> 2", round_half_up(1.5) == 2)
check("2.4 -> 2", round_half_up(2.4) == 2)
check("-2.5 -> -2 or -3", round_half_up(-2.5) in (-2, -3))

print("[5/5] filter_centroid")
centroids = np.array([[[100.0, 100.0]], [[900.0, 900.0]]])  # (2,1,2)
stats = np.array([["a"], ["b"]], dtype=object)
ideal = np.array([102.0, 98.0])
diag = 1000.0
fc, fs = filter_centroid(centroids, diag, ideal, stats, distance_percentage=0.05)
check("near centroid kept", len(fc) == 1 and np.allclose(fc[0], [100, 100]))
check("stats aligned", fs[0][0] == "a")

print(f"\n结果: {passed} 通过, {failed} 失败")
sys.exit(1 if failed else 0)
