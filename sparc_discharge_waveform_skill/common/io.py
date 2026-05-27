"""公共输入输出工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def read_yaml(path: str | Path) -> dict[str, Any]:
    """读取 YAML 配置文件。"""
    if yaml is None:
        raise RuntimeError("缺少 PyYAML 依赖，请先安装 pyyaml。")

    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError(f"YAML 顶层必须是对象: {file_path}")
    return data


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    """写出 JSON 文件。"""
    file_path = Path(path)
    ensure_parent(file_path)
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def write_text(path: str | Path, content: str) -> None:
    """写出文本文件。"""
    file_path = Path(path)
    ensure_parent(file_path)
    with file_path.open("w", encoding="utf-8") as file:
        file.write(content)


def ensure_parent(path: str | Path) -> None:
    """确保目标文件父目录存在。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在，并返回 Path 对象。"""
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path
