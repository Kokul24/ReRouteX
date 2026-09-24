"""
Fleet Coordinator Agent – central intelligence for multi-agent coordination.

Responsibilities:
  - Task assignment with cost-based optimization
  - Dynamic replanning when disruptions occur
  - Collision prevention via reservation table
  - Agent communication orchestration
  - Decision explanation generation
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import random

from models.types import (
    RobotStatus, Position, Task, Order, OrderStatus, TaskPhase,
    AgentMessage, EventType, Event
)
from agents.robot import RobotAgent
from environment.warehouse import Warehouse
from search.astar import astar_search, AStarResult
from planning.reservation import ReservationTable


class FleetCoordinator:
    """
    The Fleet Coordinator agent.

    Manages the robot fleet, assigns tasks, handles disruptions,
    and produces detailed explanations for the terminal panel.
    """

    def __init__(self, warehouse: Warehouse, settings: dict):
        self.warehouse = warehouse
        self.settings = settings
        self.robots: Dict[str, RobotAgent] = {}
        self.reservation_table = ReservationTable()
        self.orders: List[Order] = []
        self.pending_orders: List[Order] = []
        self.completed_orders: List[Order] = []
        self.messages: List[AgentMessage] = []
        self.decision_log: List[str] = []
        self.event_log: List[str] = []
        self.explanation_lines: List[str] = []
        self.current_tick: int = 0
        self.order_counter: int = 200
        self.total_replans: int = 0
        self.conflicts_prevented: int = 0
        self.collisions: int = 0
        self.costs = settings.get('costs', {})
        self.congestion_weight = self.costs.get('congestion_penalty', 3.0)

    def register_robot(self, robot: RobotAgent):
        """Register a robot with the coordinator."""
        self.robots[robot.robot_id] = robot

    def add_order(self, order: Order):
        """Add an order to the pending queue."""
        if order.pickup_aisle in self.warehouse.pickup_points:
            order.pickup_position = self.warehouse.pickup_points[order.pickup_aisle]
        self.pending_orders.append(order)
        self.orders.append(order)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _add_message(self, sender: str, receiver: str, content: str):
        """Record an agent message."""
        msg = AgentMessage(
            sender=sender, receiver=receiver, content=content,
            tick=self.current_tick, timestamp=self._timestamp()
        )
        self.messages.append(msg)

    def _add_event(self, text: str):
        """Record an event log entry."""
        self.event_log.append(f"{self._timestamp()} {text}")

    def _add_explanation(self, lines: List[str]):
        """Set current explanation lines."""
        self.explanation_lines = lines

    def _get_robot_positions(self) -> Dict[str, Tuple[int, int]]:
        """Get all robot positions."""
        return {rid: r.pos_tuple for rid, r in self.robots.items()
                if r.status != RobotStatus.FAILED}

    # ================================================================
    # TASK ASSIGNMENT
    # ================================================================

    def _calculate_assignment_cost(self, robot: RobotAgent, order: Order) -> Tuple[float, List[str]]:
        """
        Calculate cost of assigning an order to a robot.

        cost = distance + workload_penalty + congestion_penalty
             + battery_penalty + delay_penalty - priority_bonus

        Returns (cost, explanation_lines)
        """
        if not robot.is_available and robot.status != RobotStatus.IDLE:
            return float('inf'), ["Robot not available"]

        if order.pickup_position is None:
            return float('inf'), ["No pickup position"]

        distance = robot.position.manhattan_distance(order.pickup_position)
        workload_pen = robot.workload * self.costs.get('workload_penalty_weight', 2.0)
        battery_pen = max(0, (30 - robot.battery) * self.costs.get('battery_penalty_weight', 0.5))
        priority_bonus = order.effective_priority * self.costs.get('priority_bonus_weight', 3.0)
        delay_pen = order.waiting_time * self.costs.get('delay_penalty_weight', 1.5)

        # Simple congestion estimate
        robot_positions = self._get_robot_positions()
        cong_pen = 0
        if order.pickup_position:
            cong_pen = self.warehouse.get_congestion_cost(
                order.pickup_position.col, order.pickup_position.row, robot_positions
            ) * self.costs.get('congestion_penalty', 3.0)

        cost = distance + workload_pen + cong_pen + battery_pen + delay_pen - priority_bonus

        explanation = [
            f"  {robot.robot_id}:",
            f"    distance       = {distance}",
            f"    workload_pen   = {workload_pen:.1f}",
            f"    battery_pen    = {battery_pen:.1f}",
            f"    congestion_pen = {cong_pen:.1f}",
            f"    delay_pen      = {delay_pen:.1f}",
            f"    priority_bonus = {priority_bonus:.1f}",
            f"    TOTAL COST     = {cost:.1f}",
        ]
        return cost, explanation

    def assign_pending_orders(self) -> List[str]:
        """Assign pending orders to available robots. Returns explanation lines."""
        if not self.pending_orders:
            return []

        all_explanation = []
        assigned = []

        for order in self.pending_orders[:]:
            order.waiting_time += 1

            # Find best robot
            best_robot = None
            best_cost = float('inf')
            candidate_explanations = []

            available = [r for r in self.robots.values()
                         if r.status == RobotStatus.IDLE and r.battery > 20
                         and r.status != RobotStatus.FAILED
                         and r.current_task is None]

            if not available:
                continue

            for robot in available:
                cost, exp = self._calculate_assignment_cost(robot, order)
                candidate_explanations.extend(exp)
                if cost < best_cost:
                    best_cost = cost
                    best_robot = robot

            if best_robot and best_cost < float('inf'):
                # Create task
                task = Task(
                    order=order,
                    phase=TaskPhase.GO_TO_PICKUP,
                    pickup_pos=order.pickup_position,
                    deliver_pos=self.warehouse.packing_pos,
                )
                order.status = OrderStatus.ASSIGNED
                order.assigned_robot = best_robot.robot_id
                best_robot.assign_task(task)
                assigned.append(order)

                # Communication
                self._add_message("Coordinator", best_robot.robot_id,
                                  f"Assign order {order.order_id} (priority {order.priority}). "
                                  f"Pickup at {order.pickup_aisle}.")
                self._add_message(best_robot.robot_id, "Coordinator",
                                  f"Order {order.order_id} accepted. Planning route to {order.pickup_aisle}.")

                # Plan path
                self._plan_robot_path(best_robot, task)

                self._add_event(f"{order.order_id} → {best_robot.robot_id}")

                all_explanation.extend([
                    f"",
                    f"[TASK ASSIGNMENT]",
                    f"Order: {order.order_id}  Priority: {order.priority}",
                    f"Pickup: {order.pickup_aisle}",
                    f"",
                    f"[CANDIDATE EVALUATION]",
                ] + candidate_explanations + [
                    f"",
                    f"[DECISION]",
                    f"Assign {order.order_id} → {best_robot.robot_id}",
                    f"Cost: {best_cost:.1f}",
                ])

        for o in assigned:
            if o in self.pending_orders:
                self.pending_orders.remove(o)

        return all_explanation

    def _plan_robot_path(self, robot: RobotAgent, task: Task):
        """Plan a path for a robot based on its current task phase."""
        if task.phase == TaskPhase.GO_TO_PICKUP and task.pickup_pos:
            goal = task.pickup_pos.to_tuple()
        elif task.phase == TaskPhase.GO_TO_PACKING and task.deliver_pos:
            goal = task.deliver_pos.to_tuple()
        elif task.phase == TaskPhase.GO_TO_CHARGE:
            goal = self.warehouse.charging_pos.to_tuple()
        else:
            return

        result = astar_search(
            start=robot.pos_tuple,
            goal=goal,
            warehouse=self.warehouse,
            robot_id=robot.robot_id,
            robot_positions=self._get_robot_positions(),
            congestion_weight=self.congestion_weight,
        )

        if result.found:
            # Check for conflicts
            conflicts = self.reservation_table.check_conflicts(
                robot.robot_id, result.path, self.current_tick
            )
            if conflicts:
                self.conflicts_prevented += len(conflicts)
                for c in conflicts:
                    pos = c.get('position') or c.get('to') or (0, 0)
                    pos_str = f"({pos[0]},{pos[1]})" if isinstance(pos, (tuple, list)) else str(pos)
                    other_bot = c.get('other_robot', 'Unknown')
                    c_type = c.get('type', 'CONFLICT')
                    self._add_message("Coordinator", robot.robot_id,
                                      f"Conflict detected at {pos_str} with {other_bot}. "
                                      f"Type: {c_type}. Adjusting.")
                    self._add_event(f"Conflict prevented: {robot.robot_id} vs {other_bot}")

                # Attempt to find alternative route avoiding conflicting cells
                conflict_cells = {c.get('position') for c in conflicts if c.get('position')}
                conflict_cells.discard(robot.pos_tuple)
                conflict_cells.discard(goal)
                if conflict_cells:
                    alt_result = astar_search(
                        start=robot.pos_tuple,
                        goal=goal,
                        warehouse=self.warehouse,
                        robot_id=robot.robot_id,
                        robot_positions=self._get_robot_positions(),
                        reserved_cells=conflict_cells,
                        congestion_weight=self.congestion_weight,
                    )
                    if alt_result.found:
                        result = alt_result

            self.reservation_table.reserve_path(robot.robot_id, result.path, self.current_tick)
            robot.set_path(result.path, Position.from_tuple(goal))

    # ================================================================
    # DISRUPTION HANDLERS
    # ================================================================

    def handle_block_aisle(self, aisle_name: str) -> List[str]:
        """Handle aisle blockage disruption."""
        if aisle_name not in self.warehouse.aisle_names:
            return [f"[ERROR] {aisle_name} does not exist.",
                    f"Available aisles: {', '.join(self.warehouse.aisle_names)}"]

        self.warehouse.block_aisle(aisle_name)
        self._add_event(f"Aisle {aisle_name} BLOCKED")

        explanation = [
            f"{'='*50}",
            f"[EVENT] Aisle {aisle_name} BLOCKED",
            f"{'='*50}",
            f"",
        ]

        # Find affected robots
        affected = []
        aisle_cells = set(self.warehouse.aisle_cells.get(aisle_name, []))

        for robot in self.robots.values():
            if robot.status == RobotStatus.FAILED:
                continue
            if robot.needs_replan(self.warehouse):
                affected.append(robot)
            elif robot.pos_tuple in aisle_cells:
                affected.append(robot)

        if not affected:
            explanation.append("[DETECTION] No robots currently affected.")
            explanation.append("All robots continue normal operation.")
            self._add_message("Coordinator", "ALL",
                              f"Aisle {aisle_name} blocked. No robots affected. Continue normal operation.")
            return explanation

        explanation.append(f"[DETECTION]")
        for r in affected:
            explanation.append(f"  {r.robot_id} is affected.")
            self._add_message(r.robot_id, "Coordinator",
                              f"{aisle_name} is blocked on my planned route.")
            self._add_message("Coordinator", r.robot_id,
                              f"Report current position and target.")
            target_str = str(r.target) if r.target else "None"
            task_str = r.current_task.order.order_id if r.current_task else "None"
            self._add_message(r.robot_id, "Coordinator",
                              f"Position: {r.position}. Target: {target_str}. Task: {task_str}. Battery: {r.battery:.0f}%")

        explanation.append(f"")
        explanation.append(f"[COORDINATOR]")
        explanation.append(f"{aisle_name} is no longer available.")
        explanation.append(f"")
        explanation.append(f"[DECISION]")
        explanation.append(f"Replanning affected robots.")
        explanation.append(f"")
        explanation.append(f"[ALGORITHM] A* Search")
        explanation.append(f"  g(n) = movement cost")
        explanation.append(f"  h(n) = Manhattan distance")
        explanation.append(f"  congestion penalty = {self.congestion_weight}")
        explanation.append(f"")

        # Replan affected robots
        for robot in affected:
            robot.status = RobotStatus.REROUTING
            robot.reroute_count += 1
            self.total_replans += 1
            self.reservation_table.clear_robot(robot.robot_id)

            if robot.current_task:
                self._plan_robot_path(robot, robot.current_task)
                if robot.current_path:
                    explanation.append(f"[RESULT] {robot.robot_id} → Alternative route found")
                    explanation.append(f"  New path length: {len(robot.current_path)} steps")
                    explanation.append(f"  Route avoids {aisle_name}")
                    self._add_message("Coordinator", robot.robot_id,
                                      f"New route calculated avoiding {aisle_name}. Path length: {len(robot.current_path)}")
                    self._add_message(robot.robot_id, "Coordinator",
                                      f"A* route accepted. Rerouting now.")
                else:
                    explanation.append(f"[RESULT] {robot.robot_id} → No alternative route. WAITING.")
                    robot.status = RobotStatus.WAITING
                    self._add_message("Coordinator", robot.robot_id,
                                      f"No alternative route available. Please wait.")
            else:
                robot.status = RobotStatus.IDLE

        # Unaffected robots
        unaffected = [r for r in self.robots.values() if r not in affected and r.status != RobotStatus.FAILED]
        if unaffected:
            explanation.append(f"")
            explanation.append(f"[SAFETY] No collision detected.")
            explanation.append(f"Localized disruption. Unaffected agents")
            explanation.append(f"continue normal operation.")
            names = ", ".join([r.robot_id for r in unaffected])
            explanation.append(f"  Unaffected: {names}")

        return explanation

    def handle_unblock_aisle(self, aisle_name: str) -> List[str]:
        """Handle aisle unblock recovery."""
        if aisle_name not in self.warehouse.aisle_names:
            return [f"[ERROR] {aisle_name} does not exist.",
                    f"Available aisles: {', '.join(self.warehouse.aisle_names)}"]

        if aisle_name not in self.warehouse.blocked_aisles:
            return [f"[INFO] {aisle_name} is not currently blocked."]

        self.warehouse.unblock_aisle(aisle_name)
        self._add_event(f"Aisle {aisle_name} UNBLOCKED")

        explanation = [
            f"{'='*50}",
            f"[EVENT] Aisle {aisle_name} UNBLOCKED",
            f"{'='*50}",
            f"",
            f"[DETECTION]",
            f"Restriction on {aisle_name} removed.",
            f"Environment state updated.",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"Aisle {aisle_name} is now clear. Reassessing routes.")

        # Check waiting robots
        waiting = [r for r in self.robots.values() if r.status == RobotStatus.WAITING]
        if waiting:
            explanation.append(f"[COORDINATOR]")
            explanation.append(f"Checking waiting robots for route recovery.")
            explanation.append(f"")
            for robot in waiting:
                self._add_message("Coordinator", robot.robot_id,
                                  f"{aisle_name} is now available. Re-evaluate route.")
                self._add_message(robot.robot_id, "Coordinator",
                                  f"Recalculating route with {aisle_name} available.")
                if robot.current_task:
                    self._plan_robot_path(robot, robot.current_task)
                    if robot.current_path:
                        explanation.append(f"[RESULT] {robot.robot_id} → Resumed with new route")
                        explanation.append(f"  Path length: {len(robot.current_path)} steps")
                        self._add_message(robot.robot_id, "Coordinator",
                                          f"New route found. Resuming movement.")
                else:
                    robot.status = RobotStatus.IDLE
                    explanation.append(f"[RESULT] {robot.robot_id} → Now IDLE")
        else:
            explanation.append(f"[COORDINATOR]")
            explanation.append(f"No waiting robots. All robots continue")
            explanation.append(f"their current routes.")

        explanation.append(f"")
        explanation.append(f"[DECISION]")
        explanation.append(f"Routes re-evaluated. Normal operation resumes.")

        return explanation

    def handle_low_battery(self, robot_id: str) -> List[str]:
        """Handle low battery disruption."""
        robot = self.robots.get(robot_id)
        if not robot:
            return [f"[ERROR] {robot_id} does not exist.",
                    f"Available robots: {', '.join(self.robots.keys())}"]

        robot.set_low_battery(8.0)
        self._add_event(f"{robot_id} LOW BATTERY")

        explanation = [
            f"{'='*50}",
            f"[EVENT] {robot_id} LOW BATTERY",
            f"{'='*50}",
            f"",
        ]

        self._add_message(robot_id, "Coordinator",
                          f"LOW BATTERY WARNING. Current level: {robot.battery:.0f}%")
        self._add_message("Coordinator", robot_id,
                          f"Report current task and position.")

        task_str = "None"
        if robot.current_task:
            task_str = robot.current_task.order.order_id
        self._add_message(robot_id, "Coordinator",
                          f"Position: {robot.position}. Task: {task_str}. Battery: {robot.battery:.0f}%")

        # Calculate distances
        dist_to_charge = robot.position.manhattan_distance(self.warehouse.charging_pos)
        dist_to_target = 0
        if robot.target:
            dist_to_target = robot.position.manhattan_distance(robot.target)

        estimated_battery_needed = dist_to_target * 0.8  # rough estimate

        explanation.extend([
            f"[{robot_id}]",
            f"  Battery: {robot.battery:.0f}%",
            f"  Distance to charging station: {dist_to_charge}",
            f"  Distance to task destination: {dist_to_target}",
            f"  Estimated battery needed: {estimated_battery_needed:.1f}%",
            f"",
            f"[COORDINATOR ANALYSIS]",
            f"  Battery = {robot.battery:.0f}%",
            f"  Required for task = {estimated_battery_needed:.1f}%",
            f"  Required for charging station = {dist_to_charge * 0.5:.1f}%",
            f"",
        ])

        if robot.battery < estimated_battery_needed:
            explanation.append(f"[DECISION]")
            explanation.append(f"  {robot_id} cannot safely complete current task.")
            explanation.append(f"  → {robot_id} → Charging Station")

            self._add_message("Coordinator", robot_id,
                              f"Battery insufficient. Go to charging station immediately.")
            self._add_message(robot_id, "Coordinator",
                              f"Understood. Heading to charging station.")

            # Save current task for reassignment
            saved_task = robot.current_task
            robot.current_task = None
            robot.current_path = []
            robot.status = RobotStatus.LOW_BATTERY

            # Plan path to charging
            charge_task = Task(
                order=Order("CHARGE", "", 0),
                phase=TaskPhase.GO_TO_CHARGE,
            )
            robot.current_task = charge_task
            self._plan_robot_path(robot, charge_task)

            # Reassign task
            if saved_task and saved_task.order.order_id != "CHARGE":
                saved_task.order.status = OrderStatus.REASSIGNED
                saved_task.order.assigned_robot = None
                explanation.append(f"")
                explanation.append(f"[TASK REASSIGNMENT]")
                explanation.append(f"  Task {saved_task.order.order_id} needs reassignment.")

                # Find replacement
                candidates = [r for r in self.robots.values()
                              if r.robot_id != robot_id
                              and r.status in (RobotStatus.IDLE, RobotStatus.MOVING)
                              and r.battery > 30
                              and r.status != RobotStatus.FAILED]

                if candidates:
                    best = None
                    best_cost = float('inf')
                    for c in candidates:
                        cost, exp = self._calculate_assignment_cost(c, saved_task.order)
                        explanation.extend(exp)
                        if cost < best_cost:
                            best_cost = cost
                            best = c

                    if best:
                        saved_task.order.assigned_robot = best.robot_id
                        saved_task.order.status = OrderStatus.ASSIGNED
                        saved_task.phase = TaskPhase.GO_TO_PICKUP
                        best.assign_task(saved_task)
                        self._plan_robot_path(best, saved_task)

                        explanation.append(f"")
                        explanation.append(f"  Task reassigned → {best.robot_id}")
                        self._add_message("Coordinator", best.robot_id,
                                          f"Task {saved_task.order.order_id} reassigned to you from {robot_id}.")
                        self._add_message(best.robot_id, "Coordinator",
                                          f"Task {saved_task.order.order_id} accepted. Planning route.")
                        self._add_event(f"Task {saved_task.order.order_id}: {robot_id} → {best.robot_id}")
                else:
                    # Put back to pending
                    saved_task.order.status = OrderStatus.PENDING
                    self.pending_orders.append(saved_task.order)
                    explanation.append(f"  No available robot. Task returned to queue.")
        else:
            explanation.append(f"[DECISION]")
            explanation.append(f"  {robot_id} can reach charging after task.")
            explanation.append(f"  Continue current task, then charge.")

        explanation.append(f"")
        explanation.append(f"[ALGORITHM] A* for route planning")

        return explanation

    def handle_restore_battery(self, robot_id: str) -> List[str]:
        """Handle battery restoration."""
        robot = self.robots.get(robot_id)
        if not robot:
            return [f"[ERROR] {robot_id} does not exist."]

        robot.restore_battery()
        self._add_event(f"{robot_id} BATTERY RESTORED")

        self._add_message(robot_id, "Coordinator",
                          f"Battery restored to {robot.battery:.0f}%. Ready for tasks.")
        self._add_message("Coordinator", robot_id,
                          f"Welcome back. Checking pending tasks.")

        explanation = [
            f"{'='*50}",
            f"[EVENT] {robot_id} BATTERY RESTORED",
            f"{'='*50}",
            f"",
            f"[{robot_id}]",
            f"  Battery: {robot.battery:.0f}%",
            f"  Status: {robot.status.name}",
            f"",
            f"[DECISION]",
            f"  {robot_id} is now available for tasks.",
        ]

        return explanation

    def handle_robot_failure(self, robot_id: str) -> List[str]:
        """Handle robot failure disruption."""
        robot = self.robots.get(robot_id)
        if not robot:
            return [f"[ERROR] {robot_id} does not exist.",
                    f"Available robots: {', '.join(self.robots.keys())}"]

        saved_task = robot.current_task
        robot.force_stop()
        self.reservation_table.clear_robot(robot_id)
        self._add_event(f"{robot_id} FAILED")

        explanation = [
            f"{'='*50}",
            f"[FAILURE] {robot_id} UNAVAILABLE",
            f"{'='*50}",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"ALERT: {robot_id} has failed. Initiating recovery.")

        if saved_task and saved_task.order.order_id != "CHARGE":
            explanation.append(f"[TASK]")
            explanation.append(f"  {saved_task.order.order_id} was assigned to {robot_id}.")
            explanation.append(f"")
            explanation.append(f"[COORDINATOR]")
            explanation.append(f"  Evaluating available robots for reassignment.")
            explanation.append(f"")

            saved_task.order.status = OrderStatus.REASSIGNED
            saved_task.order.assigned_robot = None

            candidates = [r for r in self.robots.values()
                          if r.robot_id != robot_id
                          and r.status != RobotStatus.FAILED
                          and r.battery > 20]

            if candidates:
                explanation.append(f"[CANDIDATES]")
                best = None
                best_cost = float('inf')
                for c in candidates:
                    dist = c.position.manhattan_distance(
                        saved_task.pickup_pos or self.warehouse.pickup_points.get(saved_task.order.pickup_aisle, c.position)
                    )
                    explanation.extend([
                        f"  {c.robot_id}:",
                        f"    distance = {dist}",
                        f"    battery  = {c.battery:.0f}%",
                        f"    workload = {c.workload}",
                    ])
                    cost = dist + c.workload * 2
                    if c.battery < 30:
                        cost += 20
                    if cost < best_cost:
                        best_cost = cost
                        best = c

                if best:
                    saved_task.order.assigned_robot = best.robot_id
                    saved_task.order.status = OrderStatus.ASSIGNED
                    saved_task.phase = TaskPhase.GO_TO_PICKUP
                    best.assign_task(saved_task)
                    self._plan_robot_path(best, saved_task)

                    explanation.extend([
                        f"",
                        f"[DECISION]",
                        f"  Assign {saved_task.order.order_id} → {best.robot_id}",
                        f"",
                        f"[ALGORITHM] A* for route planning",
                    ])

                    self._add_message("Coordinator", best.robot_id,
                                      f"Task {saved_task.order.order_id} reassigned from failed {robot_id}.")
                    self._add_message(best.robot_id, "Coordinator",
                                      f"Task accepted. Calculating route.")
                    self._add_event(f"Task {saved_task.order.order_id}: {robot_id} → {best.robot_id}")
            else:
                saved_task.order.status = OrderStatus.PENDING
                self.pending_orders.append(saved_task.order)
                explanation.append(f"  No available candidates. Task queued.")
        else:
            explanation.append(f"[INFO] {robot_id} had no active task.")

        return explanation

    def handle_restore_robot(self, robot_id: str) -> List[str]:
        """Handle robot restoration."""
        robot = self.robots.get(robot_id)
        if not robot:
            return [f"[ERROR] {robot_id} does not exist."]

        robot.restore()
        self._add_event(f"{robot_id} RESTORED")

        self._add_message(robot_id, "Coordinator",
                          f"Systems online. Battery: {robot.battery:.0f}%. Ready for tasks.")
        self._add_message("Coordinator", robot_id,
                          f"Welcome back online. Checking pending tasks.")

        explanation = [
            f"{'='*50}",
            f"[EVENT] {robot_id} RESTORED",
            f"{'='*50}",
            f"",
            f"[{robot_id}]",
            f"  Status: {robot.status.name}",
            f"  Battery: {robot.battery:.0f}%",
            f"",
            f"[DECISION]",
            f"  {robot_id} is now available for tasks.",
        ]

        return explanation

    def handle_robot_recover(self, robot_id: str) -> List[str]:
        """
        Handle a RECOVER request. Validates that the robot is actually
        FAILED before delegating to the existing restore logic, so an
        accidental RECOVER on a healthy robot doesn't silently reset it.
        """
        robot = self.robots.get(robot_id)
        if not robot:
            return [f"[ERROR] {robot_id} does not exist.",
                    f"Available robots: {', '.join(self.robots.keys())}"]

        if robot.status != RobotStatus.FAILED:
            return [f"[ERROR] {robot_id} is not currently in FAILED state.",
                    f"Current status: {robot.status.name}"]

        return self.handle_restore_robot(robot_id)

    def handle_human_enter(self, aisle_name: str) -> List[str]:
        """Handle human entering an aisle."""
        if aisle_name not in self.warehouse.aisle_names:
            return [f"[ERROR] {aisle_name} does not exist.",
                    f"Available aisles: {', '.join(self.warehouse.aisle_names)}"]

        human_pos = self.warehouse.add_human(aisle_name)
        if not human_pos:
            return [f"[ERROR] Could not place human in {aisle_name}."]

        self._add_event(f"HUMAN entered {aisle_name}")

        explanation = [
            f"{'='*50}",
            f"[EVENT] HUMAN WORKER entered {aisle_name}",
            f"{'='*50}",
            f"",
            f"[SAFETY ALERT]",
            f"  Human position: {human_pos}",
            f"  Safety radius: {self.warehouse.safety_radius} cells",
            f"  SAFETY > THROUGHPUT",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"SAFETY ALERT: Human worker detected in {aisle_name}. "
                          f"Safety zone active. Radius: {self.warehouse.safety_radius} cells.")

        # Check affected robots
        affected = []
        for robot in self.robots.values():
            if robot.status == RobotStatus.FAILED:
                continue
            dist = robot.position.manhattan_distance(human_pos)
            if dist < self.warehouse.safety_radius:
                affected.append((robot, 'NEAR', dist))
            elif robot.needs_replan(self.warehouse):
                affected.append((robot, 'PATH', dist))

        if affected:
            explanation.append(f"[DETECTION]")
            for robot, reason, dist in affected:
                if reason == 'NEAR':
                    explanation.append(f"  {robot.robot_id}: Within safety zone (dist={dist})")
                    robot.status = RobotStatus.STOPPED
                    robot.current_path = []
                    self._add_message(robot.robot_id, "Coordinator",
                                      f"Human detected! Distance: {dist}. STOPPING.")
                    self._add_message("Coordinator", robot.robot_id,
                                      f"STOP immediately. Safety protocol active.")
                else:
                    explanation.append(f"  {robot.robot_id}: Path crosses safety zone")
                    robot.status = RobotStatus.REROUTING
                    robot.reroute_count += 1
                    self.total_replans += 1
                    self.reservation_table.clear_robot(robot.robot_id)
                    if robot.current_task:
                        self._plan_robot_path(robot, robot.current_task)
                    self._add_message(robot.robot_id, "Coordinator",
                                      f"Path blocked by safety zone. Requesting reroute.")
                    self._add_message("Coordinator", robot.robot_id,
                                      f"Replanning route to avoid safety zone in {aisle_name}.")

            explanation.extend([
                f"",
                f"[DECISION]",
                f"  Safety zones enforced.",
                f"  Affected robots stopped or rerouted.",
                f"  SAFETY > THROUGHPUT",
            ])
        else:
            explanation.append(f"[DETECTION] No robots in immediate danger.")
            explanation.append(f"Safety zone active. Robots will avoid area.")

        return explanation

    def handle_human_exit(self, aisle_name: str) -> List[str]:
        """Handle human leaving an aisle."""
        if aisle_name not in self.warehouse.human_positions:
            return [f"[INFO] No human worker in {aisle_name}."]

        self.warehouse.remove_human(aisle_name)
        self._add_event(f"HUMAN exited {aisle_name}")

        explanation = [
            f"{'='*50}",
            f"[EVENT] HUMAN WORKER exited {aisle_name}",
            f"{'='*50}",
            f"",
            f"[DETECTION]",
            f"  Safety zone in {aisle_name} cleared.",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"Safety zone in {aisle_name} cleared. Resuming operations.")

        # Resume stopped robots
        stopped = [r for r in self.robots.values() if r.status in (RobotStatus.STOPPED, RobotStatus.WAITING)]
        for robot in stopped:
            if robot.current_task:
                self._plan_robot_path(robot, robot.current_task)
                explanation.append(f"[RESULT] {robot.robot_id} → Resumed")
                self._add_message(robot.robot_id, "Coordinator",
                                  f"Safety zone cleared. Resuming route.")
            else:
                robot.status = RobotStatus.IDLE

        explanation.extend([
            f"",
            f"[DECISION]",
            f"  Safety restriction removed.",
            f"  Normal operation resumes.",
        ])

        return explanation

    def handle_urgent_order(self) -> List[str]:
        """Handle an urgent order event."""
        self.order_counter += 1
        order = Order(
            order_id=f"O{self.order_counter}",
            pickup_aisle=random.choice(self.warehouse.aisle_names),
            priority=10,
            status=OrderStatus.PENDING,
            created_tick=self.current_tick,
        )
        if order.pickup_aisle in self.warehouse.pickup_points:
            order.pickup_position = self.warehouse.pickup_points[order.pickup_aisle]

        self.pending_orders.insert(0, order)
        self.orders.append(order)
        self._add_event(f"URGENT ORDER {order.order_id}")

        explanation = [
            f"{'='*50}",
            f"[EVENT] URGENT ORDER {order.order_id}",
            f"{'='*50}",
            f"",
            f"  Priority: {order.priority} (URGENT)",
            f"  Pickup: {order.pickup_aisle}",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"URGENT ORDER {order.order_id} received. Priority: {order.priority}.")

        # Immediate assignment attempt
        assign_exp = self.assign_pending_orders()
        explanation.extend(assign_exp)

        return explanation

    def handle_order_surge(self) -> List[str]:
        """Handle order surge / flash sale event."""
        surge_count = self.settings.get('tasks', {}).get('surge_count', 5)
        self._add_event(f"ORDER SURGE: {surge_count} new orders")

        explanation = [
            f"{'='*50}",
            f"[EVENT] ORDER SURGE - FLASH SALE",
            f"{'='*50}",
            f"",
            f"  {surge_count} new orders incoming!",
            f"",
        ]

        self._add_message("Coordinator", "ALL",
                          f"ORDER SURGE! {surge_count} new orders received. Initiating mass allocation.")

        new_orders = []
        for i in range(surge_count):
            self.order_counter += 1
            priority = random.randint(1, 5)
            aisle = random.choice(self.warehouse.aisle_names)
            order = Order(
                order_id=f"O{self.order_counter}",
                pickup_aisle=aisle,
                priority=priority,
                status=OrderStatus.PENDING,
                created_tick=self.current_tick,
            )
            if aisle in self.warehouse.pickup_points:
                order.pickup_position = self.warehouse.pickup_points[aisle]
            self.pending_orders.append(order)
            self.orders.append(order)
            new_orders.append(order)
            explanation.append(f"  {order.order_id}: {aisle} (priority {priority})")

        # Sort by effective priority
        self.pending_orders.sort(key=lambda o: -o.effective_priority)

        explanation.extend([
            f"",
            f"[COORDINATOR]",
            f"  Sorting by effective priority (aging applied).",
            f"  Allocating to available robots.",
            f"",
        ])

        assign_exp = self.assign_pending_orders()
        explanation.extend(assign_exp)

        remaining = len(self.pending_orders)
        if remaining > 0:
            explanation.append(f"")
            explanation.append(f"[QUEUE] {remaining} orders still pending.")
            explanation.append(f"  Will be assigned as robots become available.")

        return explanation

    def get_status(self) -> List[str]:
        """Generate STATUS display."""
        lines = [
            f"{'='*50}",
            f"WAREHOUSE STATUS",
            f"{'='*50}",
            f"",
        ]
        for aisle in self.warehouse.aisle_names:
            state = "BLOCKED" if aisle in self.warehouse.blocked_aisles else "OPEN"
            human = " [HUMAN]" if aisle in self.warehouse.human_positions else ""
            lines.append(f"  {aisle}: {state}{human}")

        lines.extend([f"", f"ROBOTS", f"{'─'*30}"])
        for robot in self.robots.values():
            status = robot.get_status_dict()
            lines.extend([
                f"  {status['id']}:",
                f"    Status:   {status['status']}",
                f"    Battery:  {status['battery']}",
                f"    Position: {status['position']}",
                f"    Task:     {status['task']}",
                f"    Workload: {status['workload']}",
            ])

        lines.extend([
            f"",
            f"ORDERS",
            f"{'─'*30}",
            f"  Completed: {len(self.completed_orders)}",
            f"  Pending:   {len(self.pending_orders)}",
            f"  Active:    {sum(1 for o in self.orders if o.status in (OrderStatus.ASSIGNED, OrderStatus.PICKING, OrderStatus.DELIVERING))}",
        ])

        return lines

    def get_help(self) -> List[str]:
        """Generate HELP display."""
        return [
            f"{'='*50}",
            f"AVAILABLE COMMANDS",
            f"{'='*50}",
            f"",
            f"  BLOCK A3          Block an aisle",
            f"  UNBLOCK A3        Unblock an aisle",
            f"",
            f"  LOW BATTERY R3    Simulate low battery",
            f"  RESTORE BATTERY R3  Restore battery",
            f"",
            f"  ROBOT FAILURE R2  Simulate robot failure",
            f"  RESTORE ROBOT R2  Restore failed robot",
            f"",
            f"  HUMAN ENTER A2    Human enters aisle",
            f"  HUMAN EXIT A2     Human exits aisle",
            f"",
            f"  URGENT ORDER      Add high-priority order",
            f"  ORDER SURGE       Flash sale simulation",
            f"",
            f"  STATUS            Show system status",
            f"  HELP              Show this help",
            f"  TERMINATE         End simulation",
            f"",
            f"  Aliases:",
            f"  FAIL R2           Same as ROBOT FAILURE R2",
            f"  RECOVER R2        Same as RESTORE ROBOT R2 (only if FAILED)",
            f"  HUMAN REMOVE A2   Same as HUMAN EXIT A2",
            f"  REMOVE HUMAN A2   Same as HUMAN EXIT A2",
            f"",
            f"  Configured aisles: {', '.join(self.warehouse.aisle_names)}",
            f"  Configured robots: {', '.join(self.robots.keys())}",
        ]

    def get_terminate_summary(self) -> List[str]:
        """Generate termination summary with final metrics."""
        completed = len(self.completed_orders)
        pending = len(self.pending_orders)
        total_dist = sum(r.total_distance for r in self.robots.values())
        total_idle = sum(r.idle_time for r in self.robots.values())
        total_wait = sum(r.waiting_time for r in self.robots.values())

        return [
            f"{'='*50}",
            f"  SIMULATION TERMINATED",
            f"{'='*50}",
            f"",
            f"  Orders completed:     {completed}",
            f"  Orders pending:       {pending}",
            f"  Total orders:         {len(self.orders)}",
            f"",
            f"  Replans:              {self.total_replans}",
            f"  Conflicts prevented:  {self.conflicts_prevented}",
            f"  Collisions:           {self.collisions}",
            f"",
            f"  Total distance:       {total_dist} cells",
            f"  Total idle time:      {total_idle} ticks",
            f"  Total waiting time:   {total_wait} ticks",
            f"",
            f"  Simulation ended successfully.",
            f"{'='*50}",
        ]

    # ================================================================
    # MAIN TICK
    # ================================================================

    def tick(self, tick_num: int):
        """Run one coordinator tick – manage robots, assign tasks, check collisions."""
        self.current_tick = tick_num
        self.reservation_table.cleanup_old(tick_num)

        battery_drain = self.settings.get('battery', {}).get('drain_per_step', 0.15)

        # Tick all robots
        for robot in self.robots.values():
            robot.tick(self.warehouse, battery_drain, tick_num)

            # Collect robot messages
            for msg in robot.outgoing_messages:
                self.messages.append(msg)

            # Handle task phase transitions for IDLE robots with tasks
            if robot.status == RobotStatus.IDLE and robot.current_task:
                task = robot.current_task
                if task.phase == TaskPhase.GO_TO_PICKUP:
                    # Robot just got assigned – plan path to pickup
                    self._plan_robot_path(robot, task)
                elif task.phase == TaskPhase.GO_TO_PACKING:
                    # Robot finished picking – plan path to packing station
                    self._plan_robot_path(robot, task)
                elif task.phase == TaskPhase.GO_TO_CHARGE:
                    # Robot needs to go charge
                    self._plan_robot_path(robot, task)
                elif task.phase == TaskPhase.DONE:
                    task.order.status = OrderStatus.COMPLETED
                    task.order.completed_tick = tick_num
                    if task.order.order_id != "CHARGE":
                        self.completed_orders.append(task.order)
                        self._add_event(f"{task.order.order_id} completed by {robot.robot_id}")
                    robot.current_task = None

            # Resume WAITING robots after a few ticks (collision wait)
            if robot.status == RobotStatus.WAITING:
                if robot.waiting_time > 3:
                    if robot.current_task:
                        self._plan_robot_path(robot, robot.current_task)
                    else:
                        robot.status = RobotStatus.IDLE

            # Auto battery check
            if (robot.battery < self.settings.get('battery', {}).get('low_threshold', 20)
                    and robot.status not in (RobotStatus.CHARGING, RobotStatus.LOW_BATTERY,
                                             RobotStatus.FAILED)
                    and robot.current_task
                    and robot.current_task.order.order_id != "CHARGE"):
                self._add_message(robot.robot_id, "Coordinator",
                                  f"Battery low: {robot.battery:.0f}%. Requesting guidance.")

        # Collision check for moving robots
        positions = {}
        for robot in self.robots.values():
            if robot.status in (RobotStatus.MOVING, RobotStatus.REROUTING):
                pt = robot.pos_tuple
                if pt in positions:
                    other_id = positions[pt]
                    # Make one robot wait
                    robot.status = RobotStatus.WAITING
                    robot.waiting_time = 0
                    self.conflicts_prevented += 1
                    self._add_message("Coordinator", robot.robot_id,
                                      f"Collision risk with {other_id}. Wait 1 step.")
                else:
                    positions[pt] = robot.robot_id

        # Assign pending orders
        self.assign_pending_orders()

        # Age pending orders
        for order in self.pending_orders:
            order.waiting_time += 1

        # Auto-generate orders periodically
        gen_interval = self.settings.get('tasks', {}).get('generation_interval', 80)
        if (self.settings.get('tasks', {}).get('auto_generate', True)
                and tick_num > 0 and tick_num % gen_interval == 0):
            self.order_counter += 1
            aisle = random.choice(self.warehouse.aisle_names)
            prange = self.settings.get('tasks', {}).get('normal_priority_range', [1, 5])
            order = Order(
                order_id=f"O{self.order_counter}",
                pickup_aisle=aisle,
                priority=random.randint(prange[0], prange[1]),
                status=OrderStatus.PENDING,
                created_tick=tick_num,
            )
            self.add_order(order)
