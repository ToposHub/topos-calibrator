"""
Session state and checkpoint definitions for measurement workflow.

This module contains pure Python classes for session state management,
extracted from Backend to avoid circular import issues.

Key components:
- MeasurementSessionState: Session state enumeration
- MeasurementCheckpoint: Checkpoint data structure for resume support
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


class MeasurementSessionState:
    """测量会话状态"""
    IDLE = "idle"              # 空闲状态
    RUNNING = "running"        # 正在测量
    RECONNECTING = "reconnecting"  # 正在重连
    SUSPENDED = "suspended"    # 已挂起（等待手动恢复）
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 已失败


@dataclass
class MeasurementCheckpoint:
    """
    测量断点数据结构

    用于在探头断开时保存当前测量状态，支持恢复测量。

    Attributes:
        cycle_queue: 待测量的色块队列 [(r, g, b, name), ...]
        completed_data: 已成功测量的数据 [{"patchName", "rgb", "x", "y", "Y"}, ...]
        current_index: 当前测量索引（失败时的索引）
        measurement_name: 测量名称（如 "色域测量"、"Gamma 测量"）
        session_state: 会话状态
        created_at: 创建时间戳
        gamut_measurements: 色域测量数据（RGBW）
        gamma_measurements: 灰阶测量数据
        reason: 断点原因（如 "disconnect", "user_cancel"）
    """
    cycle_queue: List[Tuple[int, int, int, str]] = field(default_factory=list)
    completed_data: List[Dict] = field(default_factory=list)
    current_index: int = 0
    measurement_name: str = ""
    session_state: str = MeasurementSessionState.IDLE
    created_at: float = 0.0
    gamut_measurements: Dict = field(default_factory=dict)
    gamma_measurements: List = field(default_factory=list)
    reason: str = ""


__all__ = [
    "MeasurementSessionState",
    "MeasurementCheckpoint",
]