"""
Reservation table and collision prevention.

Implements space-time reservations to prevent:
  1. Vertex collisions (two robots in the same cell at the same time)
  2. Edge-swap collisions (robots swapping positions simultaneously)
"""

from typing import Dict, Set, Tuple, Optional, List
from models.types import AgentMessage


class ReservationTable:
    """Manages cell reservations across timesteps for collision prevention."""

    def __init__(self):
        # (col, row, timestep) -> robot_id
        self._reservations: Dict[Tuple[int, int, int], str] = {}
        # (col1, row1, col2, row2, timestep) -> robot_id  (edge reservations)
        self._edge_reservations: Dict[Tuple[int, int, int, int, int], str] = {}

    def reserve_path(self, robot_id: str, path: List[Tuple[int, int]], start_step: int):
        """Reserve all cells along a robot's planned path."""
        # Clear old reservations for this robot
        self.clear_robot(robot_id)
        for i, (col, row) in enumerate(path):
            step = start_step + i
            self._reservations[(col, row, step)] = robot_id
            # Edge reservation
            if i > 0:
                prev = path[i - 1]
                self._edge_reservations[(prev[0], prev[1], col, row, step)] = robot_id

    def clear_robot(self, robot_id: str):
        """Remove all reservations for a specific robot."""
        to_remove = [k for k, v in self._reservations.items() if v == robot_id]
        for k in to_remove:
            del self._reservations[k]
        to_remove_edge = [k for k, v in self._edge_reservations.items() if v == robot_id]
        for k in to_remove_edge:
            del self._edge_reservations[k]

    def check_vertex_conflict(self, col: int, row: int, step: int, robot_id: str) -> Optional[str]:
        """Check if a cell is reserved by another robot at a given timestep."""
        key = (col, row, step)
        reserved_by = self._reservations.get(key)
        if reserved_by and reserved_by != robot_id:
            return reserved_by
        return None

    def check_edge_conflict(
        self, from_col: int, from_row: int, to_col: int, to_row: int,
        step: int, robot_id: str
    ) -> Optional[str]:
        """Check for edge-swap conflicts (two robots swapping positions)."""
        # Check if another robot is moving from (to) to (from) at the same step
        reverse_key = (to_col, to_row, from_col, from_row, step)
        reserved_by = self._edge_reservations.get(reverse_key)
        if reserved_by and reserved_by != robot_id:
            return reserved_by
        return None

    def check_conflicts(
        self, robot_id: str, path: List[Tuple[int, int]], start_step: int
    ) -> List[dict]:
        """Check an entire path for conflicts. Returns list of conflict descriptions."""
        conflicts = []
        for i, (col, row) in enumerate(path):
            step = start_step + i
            # Vertex conflict
            vc = self.check_vertex_conflict(col, row, step, robot_id)
            if vc:
                conflicts.append({
                    'type': 'VERTEX',
                    'position': (col, row),
                    'step': step,
                    'other_robot': vc,
                    'robot': robot_id,
                })
            # Edge conflict
            if i > 0:
                prev = path[i - 1]
                ec = self.check_edge_conflict(prev[0], prev[1], col, row, step, robot_id)
                if ec:
                    conflicts.append({
                        'type': 'EDGE_SWAP',
                        'position': (col, row),
                        'from': prev,
                        'to': (col, row),
                        'step': step,
                        'other_robot': ec,
                        'robot': robot_id,
                    })
        return conflicts

    def get_reserved_cells_at_step(self, step: int, exclude_robot: str = "") -> Set[Tuple[int, int]]:
        """Get all reserved cells at a given timestep, optionally excluding a robot."""
        cells = set()
        for (col, row, s), rid in self._reservations.items():
            if s == step and rid != exclude_robot:
                cells.add((col, row))
        return cells

    def cleanup_old(self, current_step: int):
        """Remove reservations from past timesteps."""
        to_remove = [k for k in self._reservations if k[2] < current_step - 2]
        for k in to_remove:
            del self._reservations[k]
        to_remove_edge = [k for k in self._edge_reservations if k[4] < current_step - 2]
        for k in to_remove_edge:
            del self._edge_reservations[k]
