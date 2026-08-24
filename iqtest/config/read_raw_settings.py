"""Generalized Read Raw（简化版）全局设置的存取。

设置由 Utilities → Generalized Read Raw… 对话框编辑，持久化到项目目录：
    <项目根>/assets/config/read_raw_settings.json
（可用环境变量 LEOPARDIQTS_CONFIG_DIR 覆盖配置目录，测试隔离用；
 旧版本保存在 ~/.leopardiqlts/ 的设置会在项目文件不存在时自动回落读取）

分析模块（如 MTF/SFR）读取 .raw 时，模块 params 中未提供的键回落到这里的全局值。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from leopardiq.utils.raw_reader import CFA_PATTERNS, GRAY_METHODS

#: 字段 schema（与 iqtest.widgets.config_form 的格式一致；
#:  本模块不依赖 PySide6，默认值提取在本地完成）
#: 注：字节序固定 little-endian、不扣黑电平（MTF 流程不需要，底层
#:  raw_reader.RawReadConfig 仍保留这两个参数供其他模块使用）
READ_RAW_FIELDS: list[dict] = [
    {
        "key": "width",
        "label": "宽度 (px)",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 65536,
        "tooltip": "0 = 按文件大小自动识别常见 sensor 分辨率",
    },
    {
        "key": "height",
        "label": "高度 (px)",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 65536,
        "tooltip": "0 = 按文件大小自动识别常见 sensor 分辨率",
    },
    {
        "key": "bit_depth",
        "label": "位深 (bit)",
        "type": "choice",
        "choices": ["16", "14", "12", "10", "8"],
        "default": "16",
        "tooltip": "sensor 位深；10/12/14-bit 按 uint16 存储读取并左移到 16bit"
        "（packed MIPI 数据需先解包）",
    },
    {
        "key": "cfa",
        "label": "CFA pattern",
        "type": "choice",
        "choices": list(CFA_PATTERNS),
        "default": "Y",
        "tooltip": "mono 选 Y；Bayer RAW 选对应 pattern",
    },
    {
        "key": "demosaic",
        "label": "Bayer 去马赛克转灰度",
        "type": "bool",
        "default": True,
        "tooltip": "勾选后 Bayer RAW 去马赛克并转全分辨率灰度；不勾选返回原始 mosaic",
    },
    {
        "key": "gray_method",
        "label": "灰度转换方法",
        "type": "choice",
        "choices": list(GRAY_METHODS),
        "default": "BT709",
        "tooltip": "去马赛克后转灰度的系数：BT709（0.2125R+0.7154G+0.0721B，浮点保留精度）"
        " / BGR2GRAY（OpenCV BT.601）",
    },
]


def default_read_raw_params() -> dict:
    """提取 schema 默认值。"""
    return {f["key"]: f.get("default") for f in READ_RAW_FIELDS}


def _project_config_dir() -> Path:
    """项目内配置目录：<项目根>/assets/config。"""
    return Path(__file__).resolve().parents[2] / "assets" / "config"


def _legacy_settings_path() -> Path:
    """旧版设置文件路径（C 盘用户目录），仅用于回落读取。"""
    return Path.home() / ".leopardiqlts" / "read_raw_settings.json"


def settings_path() -> Path:
    """设置文件路径（LEOPARDIQTS_CONFIG_DIR 可覆盖配置目录，测试隔离用）。"""
    root = os.environ.get("LEOPARDIQTS_CONFIG_DIR")
    base = Path(root) if root else _project_config_dir()
    return base / "read_raw_settings.json"


def _load_saved_dict() -> dict:
    """读取已保存的设置 dict：优先项目目录文件，缺失时回落旧版用户目录文件
    （环境变量覆盖配置目录时——如测试隔离——不做旧版回落）。"""
    candidates = [settings_path()]
    if not os.environ.get("LEOPARDIQTS_CONFIG_DIR"):
        candidates.append(_legacy_settings_path())
    for path in candidates:
        if not path.is_file():
            continue
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(saved, dict):
            return saved
    return {}


def get_read_raw_params() -> dict:
    """读取全局 Read Raw 参数 = 默认值 ← 已保存文件（缺省/损坏时回退默认值）。"""
    params = default_read_raw_params()
    saved = _load_saved_dict()
    for key in params:
        if key in saved and saved[key] is not None:
            params[key] = saved[key]
    return params


def save_read_raw_params(values: dict) -> Path:
    """保存全局 Read Raw 参数，返回写入路径。"""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    params = default_read_raw_params()
    for key in params:
        if key in values and values[key] is not None:
            params[key] = values[key]
    params["bit_depth"] = str(params["bit_depth"])  # choice 控件以字符串保存
    path.write_text(
        json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
