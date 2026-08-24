"""
Validation script for Phase 1.1: image_io and image_preprocess extraction.
"""
import sys
sys.path.insert(0, r"F:\project\python\LeopardIQTest_Software")

import numpy as np

# ── Test 1: Module import ────────────────────────────────────────
print("[1/6] Testing module imports...")
try:
    from leopardiq.utils import (
        read_raw_image,
        read_raw_image_from_config,
        read_mtf_image,
        load_image_stack,
        load_image_stack_with_validation,
        get_black_level,
        apply_black_level_correction,
        split_bayer_channels,
        get_bayer_index,
        bayer_to_luminance,
        create_average_filter,
        prepare_bayer_images,
    )
    print("  ✅ All imports successful")
except Exception as e:
    print(f"  ❌ Import failed: {e}")
    sys.exit(1)

# ── Test 2: read_raw_image (mock) ────────────────────────────────
print("[2/6] Testing read_raw_image...")
try:
    # Create a mock raw file
    mock_data = np.arange(100, dtype=np.uint16)
    temp_path = r"F:\project\python\LeopardIQTest_Software\tests\_mock.raw"
    import os
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    mock_data.tofile(temp_path)

    img = read_raw_image(temp_path, width=10, height=10, dtype=np.uint16, channels=1)
    assert img.shape == (10, 10, 1), f"Expected (10,10,1), got {img.shape}"
    assert img.dtype == np.float32, f"Expected float32, got {img.dtype}"
    print(f"  ✅ read_raw_image OK, shape={img.shape}, dtype={img.dtype}")
except Exception as e:
    print(f"  ❌ read_raw_image failed: {e}")

# ── Test 3: Black level functions ────────────────────────────────
print("[3/6] Testing black level functions...")
try:
    test_img = np.ones((100, 100, 4), dtype=np.float32) * 64.0
    test_img[:, :, 0] = 60.0  # R
    test_img[:, :, 1] = 65.0  # Gr
    test_img[:, :, 2] = 62.0  # Gb
    test_img[:, :, 3] = 69.0  # B

    bl_overall, bl_per_ch = get_black_level(test_img)
    assert abs(bl_overall - 64.0) < 0.1, f"Expected ~64.0, got {bl_overall}"
    assert len(bl_per_ch) == 4, f"Expected 4 channels, got {len(bl_per_ch)}"
    print(f"  ✅ get_black_level OK: overall={bl_overall:.2f}, per_ch={bl_per_ch}")

    corrected = apply_black_level_correction(test_img, 64.0)
    assert corrected.min() >= 0, "Negative values after BLC!"
    print(f"  ✅ apply_black_level_correction OK")
except Exception as e:
    print(f"  ❌ Black level functions failed: {e}")

# ── Test 4: Bayer channel splitting ──────────────────────────────
print("[4/6] Testing Bayer channel splitting...")
try:
    # Create a 10x10 Bayer pattern image
    bayer = np.zeros((10, 10), dtype=np.float32)
    bayer[0::2, 0::2] = 1.0   # R
    bayer[0::2, 1::2] = 2.0   # Gr
    bayer[1::2, 0::2] = 3.0   # Gb
    bayer[1::2, 1::2] = 4.0   # B

    channels = split_bayer_channels(bayer)
    assert channels.shape == (5, 5, 4), f"Expected (5,5,4), got {channels.shape}"
    assert channels[0, 0, 0] == 1.0, "R channel mismatch"
    assert channels[0, 0, 1] == 2.0, "Gr channel mismatch"
    assert channels[0, 0, 2] == 3.0, "Gb channel mismatch"
    assert channels[0, 0, 3] == 4.0, "B channel mismatch"
    print(f"  ✅ split_bayer_channels OK, shape={channels.shape}")
except Exception as e:
    print(f"  ❌ Bayer splitting failed: {e}")

# ── Test 5: Bayer to luminance ───────────────────────────────────
print("[5/6] Testing bayer_to_luminance...")
try:
    cfa = ["R", "Gr", "Gb", "B"]
    # Create a 4-channel image: R=100, Gr=200, Gb=200, B=50
    test_bayer = np.zeros((10, 10, 4), dtype=np.float32)
    test_bayer[:, :, 0] = 100.0  # R
    test_bayer[:, :, 1] = 200.0  # Gr
    test_bayer[:, :, 2] = 200.0  # Gb
    test_bayer[:, :, 3] = 50.0   # B

    luma = bayer_to_luminance(test_bayer, cfa)
    # Y = 0.2126*100 + 0.7152*200 + 0.0722*50 = 21.26 + 143.04 + 3.61 = 167.91
    expected = 0.2126 * 100 + 0.7152 * 200 + 0.0722 * 50
    assert abs(luma[0, 0] - expected) < 0.1, f"Expected ~{expected:.2f}, got {luma[0, 0]:.2f}"
    print(f"  ✅ bayer_to_luminance OK: value={luma[0,0]:.2f} (expected ~{expected:.2f})")
except Exception as e:
    print(f"  ❌ Luminance conversion failed: {e}")

# ── Test 6: Average filter ───────────────────────────────────────
print("[6/6] Testing average filter...")
try:
    f = create_average_filter(size=9)
    assert f.shape == (9, 9), f"Expected (9,9), got {f.shape}"
    assert abs(f.sum() - 1.0) < 1e-10, f"Filter sum should be 1.0, got {f.sum()}"
    print(f"  ✅ create_average_filter OK, shape={f.shape}, sum={f.sum():.6f}")
except Exception as e:
    print(f"  ❌ Average filter failed: {e}")

# ── Cleanup ──────────────────────────────────────────────────────
try:
    os.remove(temp_path)
    os.rmdir(os.path.dirname(temp_path))
except:
    pass

print("\n" + "=" * 50)
print("Phase 1.1 validation complete!")
print("=" * 50)
