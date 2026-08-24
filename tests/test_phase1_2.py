"""Phase 1.2 验证测试：结果保存与 PASS/FAIL 判定。"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leopardiq.utils import (
    evaluate_pass_fail,
    pad_channel_data,
    save_results_csv,
    save_results_json,
    validate_metrics,
    validate_metrics_ordered,
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


print("[1/4] evaluate_pass_fail 通用判定器")
check("upper PASS", evaluate_pass_fail(5, 10, "upper") == "PASS")
check("upper FAIL", evaluate_pass_fail(15, 10, "upper") == "FAIL")
check("upper array abs", evaluate_pass_fail(np.array([-8, 5]), 10) == "PASS")
check("lower scalar PASS", evaluate_pass_fail(0.85, 0.8, "lower") == "PASS")
check("lower scalar FAIL", evaluate_pass_fail(0.7, 0.8, "lower") == "FAIL")
check("lower list PASS", evaluate_pass_fail([0.9, 0.85], [0.8, 0.8], "lower") == "PASS")
check("lower list FAIL", evaluate_pass_fail([0.9, 0.5], [0.8, 0.8], "lower") == "FAIL")
check("range PASS", evaluate_pass_fail(3, 5, "range") == "PASS")
check("range FAIL", evaluate_pass_fail(-7, 5, "range") == "FAIL")

print("[2/4] validate_metrics（key 命名规则推断模式）")
criteria = {"dp_cold": 10, "ri_tl": 0.8, "oc_shift_x": 20}
values = {"dp_cold": 5, "ri_tl": 0.85, "oc_shift_x": -15}
overall, keys, statuses = validate_metrics(criteria, values)
check("all PASS", overall == "PASS" and statuses == ["PASS"] * 3, f"{statuses}")
check("key order", keys == ["dp_cold", "ri_tl", "oc_shift_x"])

values_fail = {"dp_cold": 50, "ri_tl": 0.85, "oc_shift_x": -15}
overall, _, statuses = validate_metrics(criteria, values_fail)
check("one FAIL -> overall FAIL", overall == "FAIL" and statuses[0] == "FAIL")

overall, keys, statuses = validate_metrics_ordered(criteria, [5, 0.85, -15])
check("ordered interface", overall == "PASS" and len(keys) == 3)

print("[3/4] pad_channel_data")
padded = pad_channel_data([np.array([1.0, 2.0, 3.0, 4.0]), 0.5], 4)
check("scalar padded to 4", padded[1].size == 4 and padded[1][0] == 0.5 and padded[1][3] == 0)
padded = pad_channel_data([np.zeros((1, 4))], 4)
check("2D squeeze", padded[0].ndim == 1)

print("[4/4] CSV / JSON 保存")
with tempfile.TemporaryDirectory() as tmp:
    keys = ["blemish", "dp_cold"]
    vals = [np.array([1, 2, 3, 4]), 5]
    stats = ["PASS", "FAIL"]

    csv_path = save_results_csv(Path(tmp) / "r.csv", list(keys), list(vals), list(stats), ["R", "Gr", "Gb", "B"])
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    check("csv exists & 6 rows", csv_path.exists() and len(lines) == 6, f"rows={len(lines)}")
    check("csv header", lines[0].startswith("Row,blemish,dp_cold"))
    check("csv no in-place mutation", keys == ["blemish", "dp_cold"] and stats == ["PASS", "FAIL"])

    csv1_path = save_results_csv(Path(tmp) / "r1.csv", ["noise"], [1.5], ["PASS"], "C")
    check("csv single channel", len(csv1_path.read_text().strip().splitlines()) == 3)

    json_path = save_results_json(Path(tmp) / "r.json", keys, vals, stats)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    check("json overall FAIL", payload["overall_status"] == "FAIL")
    check("json metrics", payload["metrics"]["dp_cold"]["value"] == 5
          and payload["metrics"]["blemish"]["status"] == "PASS")
    check("json auto PASS", json.loads(save_results_json(
        Path(tmp) / "r2.json", ["a"], [1], ["PASS"]).read_text())["overall_status"] == "PASS")

print(f"\n结果: {passed} 通过, {failed} 失败")
sys.exit(1 if failed else 0)
