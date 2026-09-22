"""
Metrics collector – tracks simulation performance indicators.
"""

from typing import Dict, List
from agents.robot import RobotAgent
from agents.coordinator import FleetCoordinator


class MetricsCollector:
    """Collects and computes simulation metrics."""

    def __init__(self, coordinator: FleetCoordinator):
        self.coordinator = coordinator

    def get_summary(self) -> Dict[str, any]:
        """Get current metrics summary."""
        robots = self.coordinator.robots
        completed = len(self.coordinator.completed_orders)
        pending = len(self.coordinator.pending_orders)
        active = sum(1 for o in self.coordinator.orders
                     if o.status.name in ('ASSIGNED', 'PICKING', 'DELIVERING'))

        total_distance = sum(r.total_distance for r in robots.values())
        total_idle = sum(r.idle_time for r in robots.values())
        total_waiting = sum(r.waiting_time for r in robots.values())
        total_reroutes = sum(r.reroute_count for r in robots.values())

        return {
            'completed_orders': completed,
            'pending_orders': pending,
            'active_orders': active,
            'total_replans': self.coordinator.total_replans,
            'conflicts_prevented': self.coordinator.conflicts_prevented,
            'collisions': self.coordinator.collisions,
            'total_distance': total_distance,
            'total_idle_time': total_idle,
            'total_waiting_time': total_waiting,
            'total_reroutes': total_reroutes,
        }

    def get_robot_utilization(self) -> Dict[str, float]:
        """Calculate robot utilization percentages."""
        result = {}
        tick = max(1, self.coordinator.current_tick)
        for rid, robot in self.coordinator.robots.items():
            active_time = tick - robot.idle_time - robot.waiting_time
            result[rid] = max(0, (active_time / tick) * 100)
        return result
