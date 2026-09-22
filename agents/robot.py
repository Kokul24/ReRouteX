"""
Robot Agent – autonomous warehouse robot.

Each robot maintains its own state, task queue, path, and battery.
Robots execute their own movement logic and report to the coordinator.
"""

from typing import Optional, List, Tuple, Dict
from models.types import (
    RobotStatus, Position, Task, Order, TaskPhase, AgentMessage
)
from search.astar import astar_search, AStarResult


class RobotAgent:
    """An autonomous robot agent operating in the warehouse."""

    def __init__(self, robot_id: str, start_col: int, start_row: int,
                 battery: float = 100.0, speed: int = 1):
        self.robot_id: str = robot_id
        self.position: Position = Position(start_col, start_row)
        self.status: RobotStatus = RobotStatus.IDLE
        self.battery: float = battery
        self.speed: int = speed

        # Task management
        self.current_task: Optional[Task] = None
        self.task_queue: List[Task] = []

        # Path following
        self.current_path: List[Tuple[int, int]] = []
        self.path_index: int = 0
        self.target: Optional[Position] = None

        # Metrics
        self.total_distance: int = 0
        self.waiting_time: int = 0
        self.reroute_count: int = 0
        self.completed_tasks: int = 0
        self.idle_time: int = 0

        # Timing
        self.pick_timer: int = 0
        self.deliver_timer: int = 0
        self.charge_wait: int = 0

        # Messages generated this tick
        self.outgoing_messages: List[AgentMessage] = []

    @property
    def pos_tuple(self) -> Tuple[int, int]:
        return self.position.to_tuple()

    @property
    def is_available(self) -> bool:
        """Robot is available for new tasks."""
        return self.status in (RobotStatus.IDLE,) and self.battery > 20

    @property
    def workload(self) -> int:
        """Number of tasks in queue plus current task."""
        return len(self.task_queue) + (1 if self.current_task else 0)

    def send_message(self, receiver: str, content: str, tick: int) -> AgentMessage:
        """Create and store an outgoing message."""
        msg = AgentMessage(
            sender=self.robot_id,
            receiver=receiver,
            content=content,
            tick=tick,
        )
        self.outgoing_messages.append(msg)
        return msg

    def assign_task(self, task: Task):
        """Accept a new task assignment."""
        if self.current_task is None:
            self.current_task = task
        else:
            self.task_queue.append(task)

    def set_path(self, path: List[Tuple[int, int]], target: Position):
        """Set a new path for the robot to follow."""
        self.current_path = path
        self.path_index = 0
        self.target = target
        if path:
            self.status = RobotStatus.MOVING

    def plan_path(self, goal: Tuple[int, int], warehouse, robot_positions: Dict[str, Tuple[int, int]],
                  congestion_weight: float = 3.0) -> AStarResult:
        """Use A* to plan a path to the goal."""
        result = astar_search(
            start=self.pos_tuple,
            goal=goal,
            warehouse=warehouse,
            robot_id=self.robot_id,
            robot_positions=robot_positions,
            congestion_weight=congestion_weight,
        )
        return result

    def tick(self, warehouse, battery_drain: float, tick_num: int):
        """Execute one simulation tick."""
        self.outgoing_messages.clear()

        if self.status == RobotStatus.FAILED:
            return

        if self.status == RobotStatus.CHARGING:
            self.battery = min(100.0, self.battery + 2.0)
            self.charge_wait += 1
            if self.battery >= 95:
                self.status = RobotStatus.IDLE
                self.send_message("Coordinator", f"Charging complete. Battery: {self.battery:.0f}%", tick_num)
            return

        if self.status == RobotStatus.WAITING:
            self.waiting_time += 1
            return

        if self.status == RobotStatus.PICKING:
            self.pick_timer += 1
            if self.pick_timer >= 5:  # 5 ticks to pick
                self.pick_timer = 0
                if self.current_task:
                    self.current_task.phase = TaskPhase.GO_TO_PACKING
                    self.send_message("Coordinator",
                                      f"Item picked for {self.current_task.order.order_id}. Heading to packing.",
                                      tick_num)
                self.status = RobotStatus.IDLE  # Will get new path from coordinator
            return

        if self.status == RobotStatus.DELIVERING:
            self.deliver_timer += 1
            if self.deliver_timer >= 4:  # 4 ticks to deliver
                self.deliver_timer = 0
                if self.current_task:
                    self.current_task.phase = TaskPhase.DONE
                    self.send_message("Coordinator",
                                      f"Order {self.current_task.order.order_id} delivered successfully.",
                                      tick_num)
                    self.completed_tasks += 1
                self.status = RobotStatus.IDLE
            return

        if self.status == RobotStatus.IDLE:
            self.idle_time += 1
            # Check task queue
            if self.current_task is None and self.task_queue:
                self.current_task = self.task_queue.pop(0)
            return

        if self.status in (RobotStatus.MOVING, RobotStatus.REROUTING):
            self._move(battery_drain, tick_num)

    def _move(self, battery_drain: float, tick_num: int):
        """Move one step along the current path."""
        if not self.current_path or self.path_index >= len(self.current_path):
            # Arrived at destination
            self._arrive(tick_num)
            return

        next_pos = self.current_path[self.path_index]
        self.position = Position(next_pos[0], next_pos[1])
        self.path_index += 1
        self.total_distance += 1
        self.battery = max(0, self.battery - battery_drain)

        if self.status == RobotStatus.REROUTING:
            self.status = RobotStatus.MOVING

        # Check if arrived
        if self.path_index >= len(self.current_path):
            self._arrive(tick_num)

    def _arrive(self, tick_num: int):
        """Handle arrival at destination."""
        if self.current_task:
            if self.current_task.phase == TaskPhase.GO_TO_PICKUP:
                self.status = RobotStatus.PICKING
                self.pick_timer = 0
                self.send_message("Coordinator",
                                  f"Arrived at pickup for {self.current_task.order.order_id}. Picking item.",
                                  tick_num)
            elif self.current_task.phase == TaskPhase.GO_TO_PACKING:
                self.status = RobotStatus.DELIVERING
                self.deliver_timer = 0
                self.send_message("Coordinator",
                                  f"Arrived at packing station. Delivering {self.current_task.order.order_id}.",
                                  tick_num)
            elif self.current_task.phase == TaskPhase.GO_TO_CHARGE:
                self.status = RobotStatus.CHARGING
                self.charge_wait = 0
                self.send_message("Coordinator",
                                  f"Arrived at charging station. Current battery: {self.battery:.0f}%",
                                  tick_num)
            else:
                self.status = RobotStatus.IDLE
        else:
            # Going to charging or idle
            if self.target and self.status != RobotStatus.CHARGING:
                self.status = RobotStatus.IDLE
            self.current_path = []

    def force_stop(self):
        """Force the robot to stop (failure)."""
        self.status = RobotStatus.FAILED
        self.current_path = []
        self.path_index = 0

    def restore(self):
        """Restore robot from failure."""
        self.status = RobotStatus.IDLE
        self.current_task = None
        self.current_path = []
        self.path_index = 0

    def set_low_battery(self, level: float = 8.0):
        """Simulate low battery."""
        self.battery = level
        self.status = RobotStatus.LOW_BATTERY

    def restore_battery(self):
        """Restore battery to full."""
        self.battery = 100.0
        if self.status in (RobotStatus.CHARGING, RobotStatus.LOW_BATTERY):
            self.status = RobotStatus.IDLE

    def needs_replan(self, warehouse) -> bool:
        """Check if current path passes through blocked/unsafe areas."""
        if not self.current_path:
            return False
        for i in range(self.path_index, len(self.current_path)):
            col, row = self.current_path[i]
            if not warehouse.is_walkable(col, row):
                return True
        return False

    def get_status_dict(self) -> dict:
        """Return a summary dict for status display."""
        task_id = self.current_task.order.order_id if self.current_task else "None"
        return {
            'id': self.robot_id,
            'status': self.status.name,
            'battery': f"{self.battery:.0f}%",
            'position': str(self.position),
            'task': task_id,
            'workload': self.workload,
            'distance': self.total_distance,
            'completed': self.completed_tasks,
            'reroutes': self.reroute_count,
        }
