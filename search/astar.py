"""
A* Search Algorithm for warehouse path planning.

Uses Manhattan distance heuristic with congestion and reservation penalties.
Produces detailed explanations for the terminal panel.
"""

import heapq
from typing import Dict, List, Tuple, Optional, Set
from models.types import Position


class AStarResult:
    """Result of an A* search, including path and explanation data."""

    def __init__(self):
        self.path: List[Tuple[int, int]] = []
        self.found: bool = False
        self.start: Tuple[int, int] = (0, 0)
        self.goal: Tuple[int, int] = (0, 0)
        self.nodes_expanded: int = 0
        self.path_cost: float = 0.0
        self.blocked_cells_encountered: int = 0
        self.congested_cells: int = 0
        self.explanation_lines: List[str] = []

    def build_explanation(self, robot_id: str) -> List[str]:
        """Generate explanation lines for the terminal panel."""
        lines = [
            f"[PATH PLANNING]",
            f"Robot: {robot_id}",
            f"",
            f"Start: ({self.start[0]},{self.start[1]})",
            f"Goal:  ({self.goal[0]},{self.goal[1]})",
            f"",
            f"Algorithm: A*",
            f"  g(n): movement cost",
            f"  h(n): Manhattan distance",
            f"  f(n): g(n) + h(n)",
            f"",
            f"Nodes expanded: {self.nodes_expanded}",
            f"Blocked cells avoided: {self.blocked_cells_encountered}",
            f"Congested cells: {self.congested_cells}",
            f"",
        ]
        if self.found:
            lines.append(f"Path found! Length: {len(self.path)} steps")
            lines.append(f"Total cost: {self.path_cost:.1f}")
        else:
            lines.append("No path found!")
        return lines


def manhattan_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Manhattan distance heuristic: h(n) = |x1-x2| + |y1-y2|."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar_search(
    start: Tuple[int, int],
    goal: Tuple[int, int],
    warehouse,
    robot_id: str = "",
    robot_positions: Optional[Dict[str, Tuple[int, int]]] = None,
    reserved_cells: Optional[Set[Tuple[int, int]]] = None,
    congestion_weight: float = 3.0,
) -> AStarResult:
    """
    A* search from start to goal on the warehouse grid.

    Parameters:
        start: (col, row) start position
        goal: (col, row) goal position
        warehouse: Warehouse instance for walkability queries
        robot_id: ID of the robot (excluded from congestion)
        robot_positions: {robot_id: (col, row)} for congestion calculation
        reserved_cells: cells to avoid (temporary reservations)
        congestion_weight: weight for congestion penalty

    Returns:
        AStarResult with path, cost, and explanation data
    """
    result = AStarResult()
    result.start = start
    result.goal = goal

    if robot_positions is None:
        robot_positions = {}
    if reserved_cells is None:
        reserved_cells = set()

    # Filter out self from robot_positions for congestion
    other_positions = {k: v for k, v in robot_positions.items() if k != robot_id}

    # Check if goal is reachable
    if not warehouse.is_walkable(goal[0], goal[1]):
        # Try nearby cells
        best_alt = None
        best_dist = float('inf')
        for dc in range(-3, 4):
            for dr in range(-3, 4):
                nc, nr = goal[0] + dc, goal[1] + dr
                if warehouse.is_walkable(nc, nr):
                    d = manhattan_distance((nc, nr), goal)
                    if d < best_dist:
                        best_dist = d
                        best_alt = (nc, nr)
        if best_alt:
            goal = best_alt
            result.goal = goal
        else:
            result.found = False
            return result

    # A* with priority queue
    # Entry: (f_cost, counter, (col, row))
    counter = 0
    open_set = []
    heapq.heappush(open_set, (0 + manhattan_distance(start, goal), counter, start))
    counter += 1

    came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
    g_score: Dict[Tuple[int, int], float] = {start: 0}
    closed: Set[Tuple[int, int]] = set()

    while open_set:
        f, _, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path
            path = []
            node = current
            while node in came_from:
                path.append(node)
                node = came_from[node]
            path.append(start)
            path.reverse()

            result.path = path
            result.found = True
            result.path_cost = g_score[current]
            result.explanation_lines = result.build_explanation(robot_id)
            return result

        if current in closed:
            continue
        closed.add(current)
        result.nodes_expanded += 1

        for neighbor in warehouse.get_neighbors(current[0], current[1]):
            if neighbor in closed:
                continue
            if neighbor in reserved_cells:
                result.blocked_cells_encountered += 1
                continue

            # Movement cost
            move_cost = 1.0

            # Congestion penalty
            cong = warehouse.get_congestion_cost(neighbor[0], neighbor[1], other_positions)
            if cong > 0:
                result.congested_cells += 1
                move_cost += cong * congestion_weight

            tentative_g = g_score[current] + move_cost

            if tentative_g < g_score.get(neighbor, float('inf')):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f_score = tentative_g + manhattan_distance(neighbor, goal)
                heapq.heappush(open_set, (f_score, counter, neighbor))
                counter += 1

    # No path found
    result.found = False
    result.explanation_lines = result.build_explanation(robot_id)
    return result
