"""
Warehouse grid environment.

Builds the grid from YAML config, tracks aisle states, blocked cells,
human positions, and provides neighbor queries for A*.
"""

from typing import Dict, List, Tuple, Optional, Set
import yaml
from models.types import CellType, Position


class Warehouse:
    """The warehouse grid environment."""

    def __init__(self, warehouse_cfg: dict, settings_cfg: dict):
        grid_cfg = settings_cfg['grid']
        self.rows: int = grid_cfg['rows']
        self.cols: int = grid_cfg['cols']
        self.cell_size: int = grid_cfg['cell_size']
        self.safety_radius: int = settings_cfg['costs']['safety_radius']

        # Grid: (col, row) -> CellType
        self.grid: Dict[Tuple[int, int], CellType] = {}
        # Aisle cells: aisle_name -> list of (col, row)
        self.aisle_cells: Dict[str, List[Tuple[int, int]]] = {}
        # Aisle blocked status
        self.blocked_aisles: Set[str] = set()
        # Human positions: aisle_name -> Position
        self.human_positions: Dict[str, Position] = {}
        # Stations
        self.charging_pos: Position = Position(0, 0)
        self.packing_pos: Position = Position(0, 0)
        self.receiving_pos: Position = Position(0, 0)
        self.shipping_pos: Position = Position(0, 0)
        # Pickup points: aisle_name -> Position
        self.pickup_points: Dict[str, Position] = {}
        # All aisle names
        self.aisle_names: List[str] = []

        self._build_grid(warehouse_cfg)

    def _build_grid(self, cfg: dict):
        """Construct the grid from warehouse config."""
        # Initialize all cells as walls
        for c in range(self.cols):
            for r in range(self.rows):
                self.grid[(c, r)] = CellType.WALL

        # Lay down corridors first (horizontal open paths)
        corridors = cfg.get('corridors', {})
        for name, corr in corridors.items():
            row = corr['row']
            for c in range(corr['col_start'], corr['col_end'] + 1):
                if 0 <= c < self.cols and 0 <= row < self.rows:
                    self.grid[(c, row)] = CellType.CORRIDOR

        # Build aisles (vertical open paths)
        for aisle_def in cfg.get('aisles', []):
            name = aisle_def['name']
            self.aisle_names.append(name)
            col = aisle_def['col']
            cells = []
            for r in range(aisle_def['row_start'], aisle_def['row_end'] + 1):
                if 0 <= col < self.cols and 0 <= r < self.rows:
                    self.grid[(col, r)] = CellType.AISLE
                    cells.append((col, r))
            self.aisle_cells[name] = cells

        # Build shelves
        for shelf_def in cfg.get('shelves', []):
            col = shelf_def['col']
            for r in range(shelf_def['row_start'], shelf_def['row_end'] + 1):
                if 0 <= col < self.cols and 0 <= r < self.rows:
                    self.grid[(col, r)] = CellType.SHELF

        # Stations
        stations = cfg.get('stations', {})
        if 'charging' in stations:
            s = stations['charging']
            pos = s['position']
            self.charging_pos = Position(pos[0], pos[1])
            sx, sy = s.get('size', [2, 2])
            for dc in range(sx):
                for dr in range(sy):
                    cp = (pos[0] + dc, pos[1] + dr)
                    if 0 <= cp[0] < self.cols and 0 <= cp[1] < self.rows:
                        self.grid[cp] = CellType.CHARGING

        if 'packing' in stations:
            s = stations['packing']
            pos = s['position']
            self.packing_pos = Position(pos[0], pos[1])
            sx, sy = s.get('size', [3, 2])
            for dc in range(sx):
                for dr in range(sy):
                    cp = (pos[0] + dc, pos[1] + dr)
                    if 0 <= cp[0] < self.cols and 0 <= cp[1] < self.rows:
                        self.grid[cp] = CellType.PACKING

        if 'receiving' in stations:
            s = stations['receiving']
            pos = s['position']
            self.receiving_pos = Position(pos[0], pos[1])
            sx, sy = s.get('size', [3, 2])
            for dc in range(sx):
                for dr in range(sy):
                    cp = (pos[0] + dc, pos[1] + dr)
                    if 0 <= cp[0] < self.cols and 0 <= cp[1] < self.rows:
                        self.grid[cp] = CellType.RECEIVING

        if 'shipping' in stations:
            s = stations['shipping']
            pos = s['position']
            self.shipping_pos = Position(pos[0], pos[1])
            sx, sy = s.get('size', [3, 2])
            for dc in range(sx):
                for dr in range(sy):
                    cp = (pos[0] + dc, pos[1] + dr)
                    if 0 <= cp[0] < self.cols and 0 <= cp[1] < self.rows:
                        self.grid[cp] = CellType.SHIPPING

        # Pickup points
        for pp in cfg.get('pickup_points', []):
            pos = pp['position']
            aisle = pp['aisle']
            self.pickup_points[aisle] = Position(pos[0], pos[1])
            if 0 <= pos[0] < self.cols and 0 <= pos[1] < self.rows:
                self.grid[(pos[0], pos[1])] = CellType.PICKUP

        # Ensure open border rows for movement
        for c in range(self.cols):
            if self.grid.get((c, 0)) == CellType.WALL:
                self.grid[(c, 0)] = CellType.CORRIDOR
            if self.grid.get((c, self.rows - 1)) == CellType.WALL:
                self.grid[(c, self.rows - 1)] = CellType.CORRIDOR
        for r in range(self.rows):
            if self.grid.get((0, r)) == CellType.WALL:
                self.grid[(0, r)] = CellType.CORRIDOR
            if self.grid.get((self.cols - 1, r)) == CellType.WALL:
                self.grid[(self.cols - 1, r)] = CellType.CORRIDOR

    def is_walkable(self, col: int, row: int) -> bool:
        """Check if a cell can be traversed by a robot."""
        if col < 0 or col >= self.cols or row < 0 or row >= self.rows:
            return False
        cell = self.grid.get((col, row), CellType.WALL)
        if cell == CellType.WALL or cell == CellType.SHELF:
            return False
        # Check if cell is in a blocked aisle
        for aisle_name in self.blocked_aisles:
            if (col, row) in self.aisle_cells.get(aisle_name, []):
                return False
        # Check human safety zones
        for aisle_name, human_pos in self.human_positions.items():
            dist = abs(col - human_pos.col) + abs(row - human_pos.row)
            if dist < self.safety_radius:
                return False
        return True

    def get_neighbors(self, col: int, row: int) -> List[Tuple[int, int]]:
        """Get walkable 4-connected neighbors."""
        neighbors = []
        for dc, dr in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nc, nr = col + dc, row + dr
            if self.is_walkable(nc, nr):
                neighbors.append((nc, nr))
        return neighbors

    def get_congestion_cost(self, col: int, row: int, robot_positions: Dict[str, Tuple[int, int]]) -> float:
        """Calculate congestion cost for a cell based on nearby robots."""
        cost = 0.0
        for rid, pos in robot_positions.items():
            dist = abs(col - pos[0]) + abs(row - pos[1])
            if dist <= 2:
                cost += 1.0
        return cost

    def block_aisle(self, aisle_name: str) -> bool:
        """Block an aisle. Returns True if successful."""
        if aisle_name in self.aisle_names:
            self.blocked_aisles.add(aisle_name)
            return True
        return False

    def unblock_aisle(self, aisle_name: str) -> bool:
        """Unblock an aisle. Returns True if it was blocked."""
        if aisle_name in self.blocked_aisles:
            self.blocked_aisles.discard(aisle_name)
            return True
        return False

    def add_human(self, aisle_name: str) -> Optional[Position]:
        """Place a human worker in an aisle. Returns position if successful."""
        if aisle_name not in self.aisle_names:
            return None
        cells = self.aisle_cells.get(aisle_name, [])
        if cells:
            mid = cells[len(cells) // 2]
            pos = Position(mid[0], mid[1])
            self.human_positions[aisle_name] = pos
            return pos
        return None

    def remove_human(self, aisle_name: str) -> bool:
        """Remove a human worker from an aisle."""
        if aisle_name in self.human_positions:
            del self.human_positions[aisle_name]
            return True
        return False

    def is_in_blocked_aisle(self, col: int, row: int) -> Optional[str]:
        """Check if a position is in a blocked aisle. Returns aisle name or None."""
        for aisle_name in self.blocked_aisles:
            if (col, row) in self.aisle_cells.get(aisle_name, []):
                return aisle_name
        return None

    def is_in_human_zone(self, col: int, row: int) -> Optional[str]:
        """Check if a position is within a human safety zone. Returns aisle name or None."""
        for aisle_name, human_pos in self.human_positions.items():
            dist = abs(col - human_pos.col) + abs(row - human_pos.row)
            if dist < self.safety_radius:
                return aisle_name
        return None
