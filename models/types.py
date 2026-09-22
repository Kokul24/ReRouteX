"""Enumerations and data classes for robot and system state."""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


class RobotStatus(Enum):
    """All possible robot states."""
    IDLE = auto()
    MOVING = auto()
    WAITING = auto()
    REROUTING = auto()
    LOW_BATTERY = auto()
    CHARGING = auto()
    FAILED = auto()
    STOPPED = auto()
    PICKING = auto()
    DELIVERING = auto()


class CellType(Enum):
    """Types of cells in the warehouse grid."""
    FLOOR = auto()
    WALL = auto()
    SHELF = auto()
    AISLE = auto()
    CHARGING = auto()
    PACKING = auto()
    RECEIVING = auto()
    SHIPPING = auto()
    PICKUP = auto()
    CORRIDOR = auto()


class EventType(Enum):
    """Types of user-triggered events."""
    BLOCK_AISLE = auto()
    UNBLOCK_AISLE = auto()
    LOW_BATTERY = auto()
    RESTORE_BATTERY = auto()
    ROBOT_FAILURE = auto()
    RESTORE_ROBOT = auto()
    HUMAN_ENTER = auto()
    HUMAN_EXIT = auto()
    URGENT_ORDER = auto()
    ORDER_SURGE = auto()
    STATUS = auto()
    HELP = auto()
    TERMINATE = auto()


class OrderStatus(Enum):
    """Order lifecycle states."""
    PENDING = auto()
    ASSIGNED = auto()
    PICKING = auto()
    DELIVERING = auto()
    COMPLETED = auto()
    REASSIGNED = auto()


class TaskPhase(Enum):
    """Phases of a robot task."""
    GO_TO_PICKUP = auto()
    PICK_ITEM = auto()
    GO_TO_PACKING = auto()
    DELIVER_ITEM = auto()
    DONE = auto()
    GO_TO_CHARGE = auto()


@dataclass
class Position:
    """Grid position."""
    col: int
    row: int

    def to_tuple(self) -> Tuple[int, int]:
        return (self.col, self.row)

    @staticmethod
    def from_tuple(t: Tuple[int, int]) -> 'Position':
        return Position(col=t[0], row=t[1])

    def manhattan_distance(self, other: 'Position') -> int:
        return abs(self.col - other.col) + abs(self.row - other.row)

    def __eq__(self, other):
        if isinstance(other, Position):
            return self.col == other.col and self.row == other.row
        return False

    def __hash__(self):
        return hash((self.col, self.row))

    def __repr__(self):
        return f"({self.col},{self.row})"


@dataclass
class Order:
    """Represents a warehouse order."""
    order_id: str
    pickup_aisle: str
    priority: int = 3
    status: OrderStatus = OrderStatus.PENDING
    assigned_robot: Optional[str] = None
    pickup_position: Optional[Position] = None
    created_tick: int = 0
    completed_tick: int = 0
    waiting_time: int = 0

    @property
    def effective_priority(self) -> float:
        """Priority increases with waiting time (priority aging)."""
        return self.priority + self.waiting_time * 0.1


@dataclass
class Task:
    """A task assigned to a robot."""
    order: Order
    phase: TaskPhase = TaskPhase.GO_TO_PICKUP
    pickup_pos: Optional[Position] = None
    deliver_pos: Optional[Position] = None


@dataclass
class AgentMessage:
    """A structured message between agents."""
    sender: str
    receiver: str
    content: str
    tick: int
    timestamp: str = ""


@dataclass
class Event:
    """A user-triggered or system event."""
    event_type: EventType
    target: str  # aisle name or robot id
    tick: int
    description: str = ""
