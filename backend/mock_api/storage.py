"""本地 JSON 数据读写工具模块"""

import json
import time
from uuid import uuid4
from pathlib import Path
from typing import Any

from backend.config import DATA_DIR


def _resolve_path(filename: str) -> Path:
    """检查文件名是否包含路径穿越，返回到 DATA_DIR 的安全路径"""
    data_dir = DATA_DIR.resolve()
    file_path = (data_dir / filename).resolve()
    try:
        file_path.relative_to(data_dir)
    except ValueError:
        raise ValueError(f"不允许访问 DATA_DIR 外部的文件: {filename}")
    return file_path


def read_json(filename: str) -> list[dict[str, Any]]:
    """从 backend/data/ 读取 JSON 文件，返回列表"""
    file_path = _resolve_path(filename)
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 格式错误 ({filename}): {e}")
    if not isinstance(data, list):
        raise ValueError(f"数据文件 {filename} 的顶层结构必须是 JSON 数组")
    return data


def write_json(filename: str, data: list[dict[str, Any]]) -> None:
    """将列表数据写入 backend/data/ 下的 JSON 文件，保持 UTF-8 和缩进"""
    file_path = _resolve_path(filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise OSError(f"写入文件失败 ({filename}): {e}")


def append_to_json(filename: str, item: dict[str, Any]) -> None:
    """向 JSON 文件中追加一条记录"""
    current = read_json(filename)
    current.append(item)
    write_json(filename, current)


def generate_booking_id(prefix: str) -> str:
    """生成稳定的 Mock Booking ID，格式: booking_{prefix}_{序号}"""
    ts = int(time.time() * 1000)
    short = str(ts)[-8:]
    return f"booking_{prefix}_{short}_{uuid4().hex[:6]}"


def generate_order_id() -> str:
    """生成稳定的 Mock Order ID，格式: order_{序号}"""
    ts = int(time.time() * 1000)
    short = str(ts)[-8:]
    return f"order_{short}_{uuid4().hex[:6]}"
