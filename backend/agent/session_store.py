"""简易 Session 存储 - 基于 JSON 文件"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config import DATA_DIR

SESSIONS_FILE = DATA_DIR / "sessions.json"


def _read_all() -> list[dict]:
    if not SESSIONS_FILE.exists():
        return []
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_all(sessions: list[dict]) -> None:
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(user_id: str, message: str, planner_output: dict) -> dict:
    """从 planner 输出创建新 session"""
    ts = int(time.time() * 1000)
    short = str(ts)[-8:]
    session_id = f"session_{short}_{uuid.uuid4().hex[:6]}"

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "message": message,
        "intent": planner_output.get("intent", {}),
        "tag_resolve_result": planner_output.get("tag_resolve_result", {}),
        "plans": planner_output.get("plans", []),
        "tool_logs": planner_output.get("tool_logs", []),
        "status": "planned",
        "selected_plan_id": None,
        "execution_result": None,
        "share_message": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    sessions = _read_all()
    sessions.append(session)
    _write_all(sessions)
    return session


def get_session(session_id: str) -> Optional[dict]:
    """根据 session_id 获取 session"""
    sessions = _read_all()
    for s in sessions:
        if s["session_id"] == session_id:
            return s
    return None


def update_session(session_id: str, patch: dict) -> Optional[dict]:
    """更新 session，返回更新后的 session 或 None"""
    sessions = _read_all()
    for i, s in enumerate(sessions):
        if s["session_id"] == session_id:
            sessions[i].update(patch)
            sessions[i]["updated_at"] = _now()
            _write_all(sessions)
            return sessions[i]
    return None


def reset_sessions() -> None:
    """清空所有 session（仅测试使用）"""
    _write_all([])
