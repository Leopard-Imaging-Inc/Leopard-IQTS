"""criteria / 模块参数的 JSON 读写与默认值管理。

单一数据源：各 panel 的 PARAMS / CRITERIA schema；
`default_criteria.json` 为由 schema 导出的参考快照（可用 export_default_criteria 重新生成）。
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_VERSION = 1


def _panel_map() -> dict:
    """延迟导入 MODULE_PANEL_MAP：panels ↔ config 存在互相依赖
    （panel 使用 config.lf_csv，store 使用 panel schema），
    顶层导入在「先 import panels」的导入顺序下会形成循环导入。"""
    from iqtest.panels import MODULE_PANEL_MAP

    return MODULE_PANEL_MAP


def default_modules_config() -> dict:
    """全部模块的默认配置（params + criteria，取自各 panel schema）。"""
    return {key: panel.default_config() for key, panel in _panel_map().items()}


def merge_modules_config(base: dict, override: dict) -> dict:
    """将 override 的 modules 深合并进 base（仅覆盖出现的 key），返回新 dict。"""
    merged: dict = {}
    for key, cfg in base.items():
        merged[key] = {
            "params": dict(cfg.get("params", {})),
            "criteria": dict(cfg.get("criteria", {})),
        }
    for key, cfg in (override or {}).items():
        if key not in _panel_map() or not isinstance(cfg, dict):
            continue  # 未知模块键忽略，保证前向兼容
        target = merged.setdefault(key, {"params": {}, "criteria": {}})
        for section in ("params", "criteria"):
            values = cfg.get(section)
            if isinstance(values, dict):
                target.setdefault(section, {}).update(values)
    return merged


def save_json(path: str | Path, data: dict) -> None:
    """写入 JSON（UTF-8、缩进 2、保留中文）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": CONFIG_VERSION, **data}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_json(path: str | Path) -> dict:
    """读取并校验 JSON 配置。

    返回 {"modules": {...}}；文件结构非法时抛出 ValueError。
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise ValueError("配置文件结构非法：缺少顶层 \"modules\" 对象")
    known = {
        k: v for k, v in data["modules"].items() if k in _panel_map()
    }
    if not known:
        raise ValueError("配置文件中不包含任何已知模块（mtf/shading/color/flare/fov）")
    return {"modules": known}


def export_default_criteria(path: str | Path) -> None:
    """导出默认配置快照（生成 iqtest/config/default_criteria.json）。"""
    save_json(path, {"modules": default_modules_config()})
