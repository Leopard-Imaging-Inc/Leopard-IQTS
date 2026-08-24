"""LenFocus 调焦软件 config.json 解析 → Generalized Read Raw 参数。

LenFocus 保存的 config.json 中 "Camera" 段描述了相机输出格式
（分辨率 / 位深 / Bayer 排列），与 Generalized Read Raw 的读取
参数一一对应（参数含义见 doc/config 参数解析.md）：

    Reso_Width / Reso_Height  → width / height
    Image_Raw_Bits            → bit_depth（10/12/14 按 uint16 存储读取并左移）
    Color (0=mono / 1=color)  → cfa="Y"+demosaic=False / 按 Bayer_Conversion 解码
    Bayer_Conversion (46~49)  → OpenCV 去马赛克码值，反查 CFA pattern

注：Black_Level 不再导入——MTF 测试流程不使用黑电平扣除
（对比度归一化使其不影响 MTF 结果），仅在导入摘要中提示其存在。

本模块不依赖 PySide6，可独立测试。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from leopardiq.utils.raw_reader import BIT_DEPTH_DTYPES, DEMOSAIC_CODES

#: OpenCV Bayer 去马赛克码值 → CFA pattern（由 DEMOSAIC_CODES 反查，
#: 与 LenFocus 的 Bayer_Conversion 取值 46~49 一一对应）
_BAYER_CODE_TO_CFA: dict[int, str] = {code: cfa for cfa, code in DEMOSAIC_CODES.items()}


def load_lf_camera_config(path: str | os.PathLike) -> dict:
    """读取 LenFocus config.json，返回 "Camera" 段原始 dict。

    Raises:
        ValueError: 文件不存在 / 非合法 JSON / 缺少 "Camera" 段。
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"配置文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"无法解析配置文件：{path.name}（{e}）") from e
    if not isinstance(data, dict) or not isinstance(data.get("Camera"), dict):
        raise ValueError(f"配置文件中缺少 \"Camera\" 配置段：{path.name}")
    return data["Camera"]


def lf_camera_to_read_raw(camera: dict) -> tuple[dict, list[str]]:
    """LenFocus "Camera" 段 → Generalized Read Raw 表单值。

    Args:
        camera: load_lf_camera_config 返回的 "Camera" 段 dict。

    Returns:
        Tuple of (params, summary):
            - params: READ_RAW_FIELDS 表单值子集
              （width / height / bit_depth / cfa / demosaic）；
            - summary: 人类可读的映射说明（含警告），供对话框展示。

    Raises:
        ValueError: 分辨率非法、位深不支持、彩色相机 Bayer 码未知。
    """
    params: dict = {}
    summary: list[str] = []

    # ── 分辨率 ──────────────────────────────────────────────
    width = int(camera.get("Reso_Width", 0) or 0)
    height = int(camera.get("Reso_Height", 0) or 0)
    if width < 8 or height < 8:
        raise ValueError(
            f"Camera 段分辨率非法：Reso_Width={width}, Reso_Height={height}"
        )
    params["width"] = width
    params["height"] = height
    summary.append(f"分辨率：{width} × {height}")

    # ── 位深 ────────────────────────────────────────────────
    bits = int(camera.get("Image_Raw_Bits", 16) or 16)
    if bits not in BIT_DEPTH_DTYPES:
        raise ValueError(
            f"不支持的 RAW 位深：Image_Raw_Bits={bits}"
            f"（支持 {sorted(BIT_DEPTH_DTYPES)}）"
        )
    params["bit_depth"] = str(bits)  # choice 控件以字符串保存
    note = "（按 uint16 存储读取并左移到 16bit）" if 8 < bits < 16 else ""
    summary.append(f"位深：{bits}-bit{note}")

    # ── 黑电平（不导入，仅提示）────────────────────────────
    black_level = float(camera.get("Black_Level", 0) or 0)
    if black_level:
        summary.append(f"黑电平：Black_Level={black_level:g}"
                       "（MTF 流程不使用黑电平扣除，未导入）")

    # ── 彩色/黑白 + Bayer 排列 ─────────────────────────────
    is_color = bool(int(camera.get("Color", 0) or 0))
    if is_color:
        code = int(camera.get("Bayer_Conversion", 0) or 0)
        cfa = _BAYER_CODE_TO_CFA.get(code)
        if cfa is None:
            raise ValueError(
                f"未知 Bayer_Conversion 码值：{code}"
                f"（已知 {sorted(_BAYER_CODE_TO_CFA)}）"
            )
        params["cfa"] = cfa
        params["demosaic"] = True
        summary.append(f"彩色 sensor：Bayer_Conversion={code} → CFA {cfa}（去马赛克转灰度）")
    else:
        params["cfa"] = "Y"
        params["demosaic"] = False
        summary.append("Mono sensor：不去马赛克（CFA = Y）")

    # ── 警告（不阻断）──────────────────────────────────────
    if not int(camera.get("RAW_Cam", 1) or 0):
        summary.append("⚠ RAW_Cam=0（YUV 相机）：该配置保存的可能不是 RAW 数据，"
                       "读取参数对 YUV 图像不适用")

    return params, summary


def load_lf_read_raw_params(path: str | os.PathLike) -> tuple[dict, list[str]]:
    """一步完成：读取 LenFocus config.json → (Read Raw 表单值, 映射说明)。"""
    return lf_camera_to_read_raw(load_lf_camera_config(path))
