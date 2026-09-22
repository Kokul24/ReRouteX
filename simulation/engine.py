"""
Simulation Engine – orchestrates the warehouse simulation.

Loads configuration, initializes agents, runs the main loop,
processes user commands, and manages the Pygame visualization.
"""

import sys
import os
import random
from typing import List, Optional, Tuple
from datetime import datetime

import yaml
import pygame

from environment.warehouse import Warehouse
from agents.robot import RobotAgent
from agents.coordinator import FleetCoordinator
from models.types import Order, OrderStatus, EventType, Position
from metrics.collector import MetricsCollector
from visualization.renderer import Renderer


class SimulationEngine:
    """Main simulation engine."""

    def __init__(self):
        self.running: bool = True
        self.paused: bool = False
        self.tick_count: int = 0
        self.terminated: bool = False

        # Load configuration
        self.settings = self._load_yaml('config/settings.yaml')
        warehouse_cfg = self._load_yaml('config/warehouse.yaml')
        robots_cfg = self._load_yaml('config/robots.yaml')
        orders_cfg = self._load_yaml('config/orders.yaml')

        # Set random seed
        seed = self.settings.get('simulation', {}).get('random_seed', 42)
        random.seed(seed)

        # Initialize warehouse
        self.warehouse = Warehouse(warehouse_cfg, self.settings)

        # Initialize coordinator
        self.coordinator = FleetCoordinator(self.warehouse, self.settings)

        # Initialize robots
        for robot_cfg in robots_cfg.get('robots', []):
            robot = RobotAgent(
                robot_id=robot_cfg['id'],
                start_col=robot_cfg['start'][0],
                start_row=robot_cfg['start'][1],
                battery=robot_cfg.get('battery', 100),
                speed=robot_cfg.get('speed', 1),
            )
            self.coordinator.register_robot(robot)

        # Load initial orders
        for order_cfg in orders_cfg.get('orders', []):
            order = Order(
                order_id=order_cfg['id'],
                pickup_aisle=order_cfg['pickup_aisle'],
                priority=order_cfg.get('priority', 3),
                status=OrderStatus.PENDING,
                created_tick=0,
            )
            self.coordinator.add_order(order)

        # Metrics
        self.metrics = MetricsCollector(self.coordinator)

        # Terminal panel content
        self.terminal_lines: List[str] = []
        self.command_input: str = ""
        self.input_active: bool = False

        # Initialize Pygame
        pygame.init()
        sim_cfg = self.settings.get('simulation', {})
        self.screen_width = sim_cfg.get('window_width', 1600)
        self.screen_height = sim_cfg.get('window_height', 900)
        self.fps = sim_cfg.get('fps', 30)
        self.tick_rate = sim_cfg.get('tick_rate', 5)

        self.screen = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption("THE WAREHOUSE THAT REROUTES ITSELF – Multi-Agent Robot Fleet Coordination")
        self.clock = pygame.time.Clock()

        # Tick accumulator for simulation speed
        self.tick_accumulator: float = 0.0

        # Initialize renderer
        self.renderer = Renderer(self.screen, self.warehouse, self.settings)

        # Welcome message
        self._add_terminal_lines([
            "═" * 50,
            "  THE WAREHOUSE THAT REROUTES ITSELF",
            "  Multi-Agent Robot Fleet Coordination",
            "  Under Dynamic Disruptions",
            "═" * 50,
            "",
            "  System initialized. Robots active.",
            "  Type HELP for available commands.",
            "  Click the command bar to enter commands.",
            "",
        ])

    def _load_yaml(self, path: str) -> dict:
        """Load a YAML configuration file."""
        if not os.path.exists(path):
            print(f"Warning: Config file {path} not found.")
            return {}
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}

    def _add_terminal_lines(self, lines: List[str]):
        """Add lines to the terminal panel."""
        self.terminal_lines.extend(lines)
        # Keep last 200 lines
        if len(self.terminal_lines) > 200:
            self.terminal_lines = self.terminal_lines[-200:]

    def process_command(self, command: str):
        """Process a user command string."""
        cmd = command.strip().upper()
        if not cmd:
            return

        self._add_terminal_lines([f"", f"> {command}", f""])

        parts = cmd.split()

        try:
            if cmd == "HELP":
                lines = self.coordinator.get_help()
                self._add_terminal_lines(lines)

            elif cmd == "STATUS":
                lines = self.coordinator.get_status()
                self._add_terminal_lines(lines)

            elif cmd == "TERMINATE":
                lines = self.coordinator.get_terminate_summary()
                self._add_terminal_lines(lines)
                self.terminated = True

            elif cmd == "URGENT ORDER":
                lines = self.coordinator.handle_urgent_order()
                self._add_terminal_lines(lines)

            elif cmd == "ORDER SURGE":
                lines = self.coordinator.handle_order_surge()
                self._add_terminal_lines(lines)

            elif len(parts) >= 2 and parts[0] == "BLOCK":
                aisle = parts[1]
                lines = self.coordinator.handle_block_aisle(aisle)
                self._add_terminal_lines(lines)

            elif len(parts) >= 2 and parts[0] == "UNBLOCK":
                aisle = parts[1]
                lines = self.coordinator.handle_unblock_aisle(aisle)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "LOW" and parts[1] == "BATTERY":
                robot_id = parts[2]
                lines = self.coordinator.handle_low_battery(robot_id)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "RESTORE" and parts[1] == "BATTERY":
                robot_id = parts[2]
                lines = self.coordinator.handle_restore_battery(robot_id)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "ROBOT" and parts[1] == "FAILURE":
                robot_id = parts[2]
                lines = self.coordinator.handle_robot_failure(robot_id)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "RESTORE" and parts[1] == "ROBOT":
                robot_id = parts[2]
                lines = self.coordinator.handle_restore_robot(robot_id)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "HUMAN" and parts[1] == "ENTER":
                aisle = parts[2]
                lines = self.coordinator.handle_human_enter(aisle)
                self._add_terminal_lines(lines)

            elif len(parts) >= 3 and parts[0] == "HUMAN" and parts[1] == "EXIT":
                aisle = parts[2]
                lines = self.coordinator.handle_human_exit(aisle)
                self._add_terminal_lines(lines)

            else:
                self._add_terminal_lines([
                    f"[ERROR] Unknown command: {command}",
                    f"Type HELP for available commands.",
                ])

        except Exception as e:
            self._add_terminal_lines([
                f"[ERROR] Command failed: {str(e)}",
                f"Type HELP for available commands.",
            ])

    def handle_events(self):
        """Process Pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if self.input_active:
                    if event.key == pygame.K_RETURN:
                        self.process_command(self.command_input)
                        self.command_input = ""
                    elif event.key == pygame.K_BACKSPACE:
                        self.command_input = self.command_input[:-1]
                    elif event.key == pygame.K_ESCAPE:
                        self.input_active = False
                        self.command_input = ""
                    else:
                        if event.unicode and event.unicode.isprintable():
                            self.command_input += event.unicode
                else:
                    if event.key == pygame.K_RETURN or event.key == pygame.K_SLASH:
                        self.input_active = True
                        self.command_input = ""
                    elif event.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Check if clicked on command bar area
                mx, my = event.pos
                cmd_bar = self.renderer.get_command_bar_rect()
                if cmd_bar and cmd_bar.collidepoint(mx, my):
                    self.input_active = True
                    self.command_input = ""
                else:
                    # Check button clicks
                    btn = self.renderer.check_button_click(mx, my)
                    if btn:
                        self.process_command(btn)

    def update(self):
        """Run one simulation update cycle."""
        if self.paused or self.terminated:
            return

        dt = self.clock.get_time() / 1000.0
        self.tick_accumulator += dt * self.tick_rate

        while self.tick_accumulator >= 1.0:
            self.tick_accumulator -= 1.0
            self.tick_count += 1
            self.coordinator.tick(self.tick_count)

    def render(self):
        """Render the current frame."""
        # Collect messages from coordinator (last 30)
        recent_messages = self.coordinator.messages[-30:] if self.coordinator.messages else []
        recent_events = self.coordinator.event_log[-15:] if self.coordinator.event_log else []

        # Build robot status info
        robot_statuses = {}
        for rid, robot in self.coordinator.robots.items():
            robot_statuses[rid] = robot.get_status_dict()

        metrics = self.metrics.get_summary()

        self.renderer.render(
            robots=self.coordinator.robots,
            terminal_lines=self.terminal_lines,
            messages=recent_messages,
            events=recent_events,
            robot_statuses=robot_statuses,
            metrics=metrics,
            command_input=self.command_input,
            input_active=self.input_active,
            paused=self.paused,
            tick=self.tick_count,
            explanation_lines=self.coordinator.explanation_lines,
        )

    def run(self):
        """Main simulation loop."""
        while self.running:
            self.handle_events()
            self.update()
            self.render()
            self.clock.tick(self.fps)

            if self.terminated:
                # Wait a moment then exit on keypress
                waiting = True
                while waiting and self.running:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            waiting = False
                            self.running = False
                        elif event.type == pygame.KEYDOWN:
                            waiting = False
                            self.running = False
                    self.clock.tick(10)

        pygame.quit()
        sys.exit(0)
