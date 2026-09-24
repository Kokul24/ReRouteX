"""
Pygame Renderer – polished warehouse visualization with integrated terminal panel.

Layout:
  LEFT  (60%): Warehouse grid visualization with robots, paths, stations
  RIGHT (40%): Terminal panel with agent communication, decisions, status, events

Design: Dark theme with vibrant accent colors for a professional presentation look.
"""

import math
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import pygame

from environment.warehouse import Warehouse
from models.types import CellType, RobotStatus, AgentMessage


# ═══════════════════════════════════════════════════════════
# COLOR PALETTE – dark professional theme
# ═══════════════════════════════════════════════════════════

class Colors:
    # Backgrounds
    BG_DARK = (14, 17, 23)
    BG_PANEL = (22, 27, 34)
    BG_CARD = (30, 37, 48)
    BG_INPUT = (38, 46, 58)
    BG_GRID = (20, 25, 32)

    # Borders
    BORDER = (48, 56, 70)
    BORDER_ACCENT = (56, 139, 253)
    BORDER_DIM = (36, 43, 55)

    # Text
    TEXT_PRIMARY = (230, 237, 243)
    TEXT_SECONDARY = (139, 148, 158)
    TEXT_DIM = (89, 97, 107)
    TEXT_ACCENT = (88, 166, 255)
    TEXT_GREEN = (63, 185, 80)
    TEXT_ORANGE = (227, 158, 53)
    TEXT_RED = (248, 81, 73)
    TEXT_PURPLE = (188, 140, 255)
    TEXT_CYAN = (57, 211, 235)

    # Warehouse cells
    FLOOR = (25, 30, 38)
    WALL = (45, 52, 65)
    SHELF = (62, 50, 30)
    SHELF_EDGE = (85, 70, 42)
    AISLE = (28, 38, 52)
    AISLE_BLOCKED = (80, 25, 25)
    CORRIDOR = (25, 33, 45)
    CHARGING = (30, 70, 50)
    PACKING = (45, 40, 75)
    RECEIVING = (35, 55, 65)
    SHIPPING = (55, 45, 55)
    PICKUP = (50, 60, 40)

    # Robots
    ROBOT_COLORS = [
        (56, 139, 253),   # R1 – blue
        (63, 185, 80),    # R2 – green
        (227, 158, 53),   # R3 – amber
        (188, 140, 255),  # R4 – purple
        (57, 211, 235),   # R5 – cyan
    ]

    ROBOT_FAILED = (130, 50, 50)
    ROBOT_CHARGING = (60, 200, 100)
    ROBOT_WAITING = (200, 200, 60)
    ROBOT_LOW_BATT = (200, 80, 30)

    # Human
    HUMAN = (255, 180, 120)
    HUMAN_ZONE = (255, 80, 80, 40)

    # Path
    PATH_ACTIVE = (56, 139, 253, 100)

    # Buttons
    BTN_BG = (40, 48, 60)
    BTN_HOVER = (55, 65, 80)
    BTN_TEXT = (200, 210, 220)
    BTN_DANGER = (120, 40, 40)
    BTN_SUCCESS = (35, 80, 50)


class Renderer:
    """Main Pygame renderer for the warehouse simulation."""

    def __init__(self, screen: pygame.Surface, warehouse: Warehouse, settings: dict):
        self.screen = screen
        self.warehouse = warehouse
        self.settings = settings
        self.width, self.height = screen.get_size()

        # Layout proportions
        self.grid_area_width = int(self.width * 0.58)
        self.panel_width = self.width - self.grid_area_width
        self.panel_x = self.grid_area_width

        # Grid rendering
        grid_cfg = settings['grid']
        self.cell_size = min(
            (self.grid_area_width - 40) // warehouse.cols,
            (self.height - 120) // warehouse.rows,
            grid_cfg['cell_size']
        )
        self.grid_offset_x = 20
        self.grid_offset_y = 60

        # Fonts
        try:
            self.font_title = pygame.font.SysFont("Menlo", 18, bold=True)
            self.font_heading = pygame.font.SysFont("Menlo", 14, bold=True)
            self.font_body = pygame.font.SysFont("Menlo", 12)
            self.font_small = pygame.font.SysFont("Menlo", 11)
            self.font_tiny = pygame.font.SysFont("Menlo", 10)
            self.font_robot = pygame.font.SysFont("Menlo", 10, bold=True)
            self.font_label = pygame.font.SysFont("Menlo", 9)
            self.font_input = pygame.font.SysFont("Menlo", 14)
        except Exception:
            self.font_title = pygame.font.SysFont(None, 22, bold=True)
            self.font_heading = pygame.font.SysFont(None, 17, bold=True)
            self.font_body = pygame.font.SysFont(None, 15)
            self.font_small = pygame.font.SysFont(None, 14)
            self.font_tiny = pygame.font.SysFont(None, 13)
            self.font_robot = pygame.font.SysFont(None, 13, bold=True)
            self.font_label = pygame.font.SysFont(None, 12)
            self.font_input = pygame.font.SysFont(None, 17)

        # Command bar rect
        self._command_bar_rect = pygame.Rect(
            self.panel_x + 10,
            self.height - 44,
            self.panel_width - 20,
            32
        )

        # Quick-action buttons (rebuilt every frame from live state — see _build_buttons)
        self.buttons: List[dict] = []
        self._build_buttons({})

        # Terminal scroll
        self.terminal_scroll = 0

        # Animation tick
        self.anim_tick = 0

    def _build_buttons(self, robots: dict):
        """
        Rebuild the quick-action buttons below the warehouse grid from the
        current warehouse/robot state.

        Buttons are generated dynamically for every configured aisle and
        robot (never hard-coded IDs), and are context-sensitive: only the
        action that is currently meaningful is shown (e.g. UNBLOCK only
        while an aisle is blocked, RECOVER only while a robot is FAILED).
        Every button's 'command' is a plain string fed straight into the
        same command parser the typed command bar uses, so buttons and
        typed commands stay perfectly in sync.
        """
        btn_y = self.grid_offset_y + self.warehouse.rows * self.cell_size + 15
        btn_w = 92
        btn_h = 22
        gap = 4
        x0 = self.grid_offset_x
        available_w = self.grid_area_width - 2 * self.grid_offset_x
        per_row = max(1, (available_w + gap) // (btn_w + gap))

        defs: List[Tuple[str, str, Tuple[int, int, int]]] = []

        # Aisle block / unblock — one button per configured aisle
        for aisle in self.warehouse.aisle_names:
            if aisle in self.warehouse.blocked_aisles:
                defs.append((f"UNBLOCK {aisle}", f"UNBLOCK {aisle}", Colors.BTN_SUCCESS))
            else:
                defs.append((f"BLOCK {aisle}", f"BLOCK {aisle}", Colors.BTN_DANGER))

        # Human enter / remove — one button per configured aisle
        for aisle in self.warehouse.aisle_names:
            if aisle in self.warehouse.human_positions:
                defs.append((f"HUMAN- {aisle}", f"HUMAN REMOVE {aisle}", Colors.BTN_BG))
            else:
                defs.append((f"HUMAN+ {aisle}", f"HUMAN ENTER {aisle}", Colors.BTN_BG))

        # Robot fail / recover — one button per configured robot
        for rid, robot in robots.items():
            if robot.status == RobotStatus.FAILED:
                defs.append((f"RECOVER {rid}", f"RECOVER {rid}", Colors.BTN_SUCCESS))
            else:
                defs.append((f"FAIL {rid}", f"FAIL {rid}", Colors.BTN_DANGER))

        # Robot low battery / restore — one button per configured robot
        # (skipped for FAILED robots, since charging is not meaningful there)
        for rid, robot in robots.items():
            if robot.status == RobotStatus.FAILED:
                continue
            if robot.status in (RobotStatus.LOW_BATTERY, RobotStatus.CHARGING):
                defs.append((f"CHARGE {rid}", f"RESTORE BATTERY {rid}", Colors.BTN_SUCCESS))
            else:
                defs.append((f"LOW BAT {rid}", f"LOW BATTERY {rid}", Colors.BTN_BG))

        # Static extras
        defs.append(("URGENT ORDER", "URGENT ORDER", Colors.BTN_BG))
        defs.append(("ORDER SURGE", "ORDER SURGE", Colors.BTN_BG))
        defs.append(("STATUS", "STATUS", Colors.BTN_BG))

        buttons = []
        for i, (label, command, color) in enumerate(defs):
            col = i % per_row
            row = i // per_row
            bx = x0 + col * (btn_w + gap)
            by = btn_y + row * (btn_h + gap)
            buttons.append({
                'rect': pygame.Rect(bx, by, btn_w, btn_h),
                'label': label,
                'command': command,
                'color': color,
            })
        self.buttons = buttons

    def get_command_bar_rect(self) -> pygame.Rect:
        """Return the command bar rectangle for click detection."""
        return self._command_bar_rect

    def check_button_click(self, mx: int, my: int) -> Optional[str]:
        """Check if a button was clicked. Returns command string or None."""
        for btn in self.buttons:
            if btn['rect'].collidepoint(mx, my):
                return btn['command']
        return None

    # ════════════════════════════════════════════════════════
    # MAIN RENDER
    # ════════════════════════════════════════════════════════

    def render(self, robots, terminal_lines, messages, events,
               robot_statuses, metrics, command_input, input_active,
               paused, tick, explanation_lines):
        """Render the complete frame."""
        self.anim_tick += 1
        self.screen.fill(Colors.BG_DARK)

        # Draw grid area
        self._draw_warehouse_grid(robots)

        # Draw robot paths and robots
        self._draw_robot_paths(robots)
        self._draw_robots(robots)

        # Draw humans
        self._draw_humans()

        # Draw station labels
        self._draw_station_labels()

        # Draw aisle labels
        self._draw_aisle_labels()

        # Draw title bar
        self._draw_title_bar(tick, paused, metrics)

        # Rebuild + draw quick-action buttons (dynamic, context-sensitive)
        self._build_buttons(robots)
        self._draw_buttons()

        # Draw right panel
        self._draw_panel(terminal_lines, messages, events,
                         robot_statuses, metrics, command_input,
                         input_active, explanation_lines)

        # Draw panel separator
        pygame.draw.line(self.screen, Colors.BORDER_ACCENT,
                         (self.panel_x, 0), (self.panel_x, self.height), 2)

        pygame.display.flip()

    # ════════════════════════════════════════════════════════
    # GRID DRAWING
    # ════════════════════════════════════════════════════════

    def _draw_warehouse_grid(self, robots):
        """Draw the warehouse grid with all cell types."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        for col in range(self.warehouse.cols):
            for row in range(self.warehouse.rows):
                x = ox + col * cs
                y = oy + row * cs
                rect = pygame.Rect(x, y, cs, cs)

                cell_type = self.warehouse.grid.get((col, row), CellType.WALL)

                # Check if in blocked aisle
                in_blocked = self.warehouse.is_in_blocked_aisle(col, row)
                in_human = self.warehouse.is_in_human_zone(col, row)

                # Choose color
                if in_blocked:
                    color = Colors.AISLE_BLOCKED
                    # Pulsing effect for blocked
                    pulse = int(20 * math.sin(self.anim_tick * 0.1))
                    color = (min(255, color[0] + pulse), color[1], color[2])
                elif cell_type == CellType.WALL:
                    color = Colors.WALL
                elif cell_type == CellType.SHELF:
                    color = Colors.SHELF
                elif cell_type == CellType.AISLE:
                    color = Colors.AISLE
                elif cell_type == CellType.CORRIDOR:
                    color = Colors.CORRIDOR
                elif cell_type == CellType.CHARGING:
                    color = Colors.CHARGING
                elif cell_type == CellType.PACKING:
                    color = Colors.PACKING
                elif cell_type == CellType.RECEIVING:
                    color = Colors.RECEIVING
                elif cell_type == CellType.SHIPPING:
                    color = Colors.SHIPPING
                elif cell_type == CellType.PICKUP:
                    color = Colors.PICKUP
                else:
                    color = Colors.FLOOR

                pygame.draw.rect(self.screen, color, rect)

                # Draw subtle grid lines
                pygame.draw.rect(self.screen, Colors.BORDER_DIM, rect, 1)

                # Shelf styling
                if cell_type == CellType.SHELF:
                    inner = pygame.Rect(x + 2, y + 2, cs - 4, cs - 4)
                    pygame.draw.rect(self.screen, Colors.SHELF_EDGE, inner, 1)
                    # Draw shelf lines
                    for sy in range(y + 6, y + cs - 2, 6):
                        pygame.draw.line(self.screen, Colors.SHELF_EDGE,
                                         (x + 3, sy), (x + cs - 3, sy), 1)

                # Human safety zone overlay
                if in_human and not in_blocked:
                    zone_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                    pulse_a = int(30 + 20 * math.sin(self.anim_tick * 0.08))
                    zone_surf.fill((255, 80, 80, pulse_a))
                    self.screen.blit(zone_surf, (x, y))

    # ════════════════════════════════════════════════════════
    # ROBOT DRAWING
    # ════════════════════════════════════════════════════════

    def _draw_robot_paths(self, robots):
        """Draw planned paths for all robots."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        for i, (rid, robot) in enumerate(robots.items()):
            if not robot.current_path or robot.status == RobotStatus.FAILED:
                continue

            color_idx = i % len(Colors.ROBOT_COLORS)
            base_color = Colors.ROBOT_COLORS[color_idx]

            # Draw path from current index onward
            for j in range(robot.path_index, len(robot.current_path)):
                col, row = robot.current_path[j]
                x = ox + col * cs + cs // 4
                y = oy + row * cs + cs // 4
                path_rect = pygame.Rect(x, y, cs // 2, cs // 2)
                path_surf = pygame.Surface((cs // 2, cs // 2), pygame.SRCALPHA)
                alpha = max(30, 90 - (j - robot.path_index) * 3)
                path_surf.fill((*base_color, alpha))
                self.screen.blit(path_surf, (x, y))

            # Draw path lines
            if len(robot.current_path) > robot.path_index + 1:
                points = []
                for j in range(robot.path_index, len(robot.current_path)):
                    col, row = robot.current_path[j]
                    px = ox + col * cs + cs // 2
                    py = oy + row * cs + cs // 2
                    points.append((px, py))
                if len(points) >= 2:
                    pygame.draw.lines(self.screen, (*base_color[:3],), False, points, 2)

    def _draw_robots(self, robots):
        """Draw all robots on the grid."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        for i, (rid, robot) in enumerate(robots.items()):
            col, row = robot.pos_tuple
            cx = ox + col * cs + cs // 2
            cy = oy + row * cs + cs // 2
            radius = cs // 2 - 3

            color_idx = i % len(Colors.ROBOT_COLORS)

            # Choose color based on status
            if robot.status == RobotStatus.FAILED:
                color = Colors.ROBOT_FAILED
            elif robot.status == RobotStatus.CHARGING:
                color = Colors.ROBOT_CHARGING
            elif robot.status == RobotStatus.WAITING or robot.status == RobotStatus.STOPPED:
                color = Colors.ROBOT_WAITING
            elif robot.status == RobotStatus.LOW_BATTERY:
                color = Colors.ROBOT_LOW_BATT
            else:
                color = Colors.ROBOT_COLORS[color_idx]

            # Glow effect
            glow_surf = pygame.Surface((cs + 8, cs + 8), pygame.SRCALPHA)
            glow_alpha = int(40 + 15 * math.sin(self.anim_tick * 0.05 + i))
            pygame.draw.circle(glow_surf, (*color, glow_alpha),
                               (cs // 2 + 4, cs // 2 + 4), radius + 5)
            self.screen.blit(glow_surf, (cx - cs // 2 - 4, cy - cs // 2 - 4))

            # Robot body
            pygame.draw.circle(self.screen, color, (cx, cy), radius)
            pygame.draw.circle(self.screen, Colors.TEXT_PRIMARY, (cx, cy), radius, 2)

            # Robot ID
            text = self.font_robot.render(rid, True, Colors.BG_DARK)
            text_rect = text.get_rect(center=(cx, cy))
            self.screen.blit(text, text_rect)

            # Battery bar under robot
            bar_w = cs - 6
            bar_h = 3
            bar_x = ox + col * cs + 3
            bar_y = oy + row * cs + cs - 5
            fill = int(bar_w * robot.battery / 100)
            bat_color = Colors.TEXT_GREEN if robot.battery > 30 else (
                Colors.TEXT_ORANGE if robot.battery > 15 else Colors.TEXT_RED
            )
            pygame.draw.rect(self.screen, Colors.BG_DARK, (bar_x, bar_y, bar_w, bar_h))
            pygame.draw.rect(self.screen, bat_color, (bar_x, bar_y, fill, bar_h))

            # Status indicator dot
            status_color = Colors.TEXT_GREEN
            if robot.status in (RobotStatus.FAILED, RobotStatus.STOPPED):
                status_color = Colors.TEXT_RED
            elif robot.status in (RobotStatus.WAITING, RobotStatus.REROUTING):
                status_color = Colors.TEXT_ORANGE
            elif robot.status == RobotStatus.CHARGING:
                status_color = Colors.TEXT_CYAN
            elif robot.status == RobotStatus.LOW_BATTERY:
                status_color = Colors.TEXT_RED
            pygame.draw.circle(self.screen, status_color,
                               (ox + col * cs + cs - 4, oy + row * cs + 4), 3)

    def _draw_humans(self):
        """Draw human workers on the grid."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        for aisle_name, pos in self.warehouse.human_positions.items():
            cx = ox + pos.col * cs + cs // 2
            cy = oy + pos.row * cs + cs // 2

            # Human figure (simple)
            # Head
            pygame.draw.circle(self.screen, Colors.HUMAN, (cx, cy - 6), 5)
            # Body
            pygame.draw.line(self.screen, Colors.HUMAN, (cx, cy - 1), (cx, cy + 6), 2)
            # Arms
            pygame.draw.line(self.screen, Colors.HUMAN, (cx - 5, cy + 2), (cx + 5, cy + 2), 2)
            # Legs
            pygame.draw.line(self.screen, Colors.HUMAN, (cx, cy + 6), (cx - 4, cy + 12), 2)
            pygame.draw.line(self.screen, Colors.HUMAN, (cx, cy + 6), (cx + 4, cy + 12), 2)

            # Label
            label = self.font_label.render(f"HUMAN", True, Colors.TEXT_RED)
            self.screen.blit(label, (cx - 15, cy + 14))

            # Safety radius visualization
            safety_r = self.warehouse.safety_radius
            zone_surf = pygame.Surface((safety_r * 2 * cs + cs, safety_r * 2 * cs + cs), pygame.SRCALPHA)
            pulse_a = int(20 + 10 * math.sin(self.anim_tick * 0.1))
            pygame.draw.circle(zone_surf, (255, 60, 60, pulse_a),
                               (safety_r * cs + cs // 2, safety_r * cs + cs // 2),
                               safety_r * cs)
            self.screen.blit(zone_surf,
                             (cx - safety_r * cs - cs // 2, cy - safety_r * cs - cs // 2))

    def _draw_station_labels(self):
        """Draw labels for stations."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        stations = [
            (self.warehouse.charging_pos, "CHARGING", Colors.CHARGING),
            (self.warehouse.packing_pos, "PACKING", Colors.PACKING),
            (self.warehouse.receiving_pos, "RECEIVING", Colors.RECEIVING),
            (self.warehouse.shipping_pos, "SHIPPING", Colors.SHIPPING),
        ]

        for pos, name, color in stations:
            x = ox + pos.col * cs
            y = oy + pos.row * cs
            label = self.font_label.render(name, True, Colors.TEXT_PRIMARY)
            # Background
            lw, lh = label.get_size()
            bg_rect = pygame.Rect(x, y + cs - 2, lw + 6, lh + 2)
            pygame.draw.rect(self.screen, (*color, ), bg_rect)
            self.screen.blit(label, (x + 3, y + cs - 1))

    def _draw_aisle_labels(self):
        """Draw aisle labels at the top of each aisle."""
        cs = self.cell_size
        ox, oy = self.grid_offset_x, self.grid_offset_y

        for aisle_name, cells in self.warehouse.aisle_cells.items():
            if cells:
                col = cells[0][0]
                row = cells[0][1]
                x = ox + col * cs + cs // 2
                y = oy + row * cs - 2

                blocked = aisle_name in self.warehouse.blocked_aisles
                color = Colors.TEXT_RED if blocked else Colors.TEXT_ACCENT
                label = self.font_label.render(aisle_name, True, color)
                lr = label.get_rect(centerx=x, bottom=y)
                self.screen.blit(label, lr)

    # ════════════════════════════════════════════════════════
    # TITLE BAR
    # ════════════════════════════════════════════════════════

    def _draw_title_bar(self, tick, paused, metrics):
        """Draw the top title bar."""
        bar_rect = pygame.Rect(0, 0, self.grid_area_width, 50)
        pygame.draw.rect(self.screen, Colors.BG_PANEL, bar_rect)
        pygame.draw.line(self.screen, Colors.BORDER, (0, 50), (self.grid_area_width, 50), 1)

        # Title
        title = self.font_title.render("THE WAREHOUSE THAT REROUTES ITSELF", True, Colors.TEXT_ACCENT)
        self.screen.blit(title, (15, 8))

        # Subtitle
        sub = self.font_tiny.render("Multi-Agent Robot Fleet Coordination Under Dynamic Disruptions", True, Colors.TEXT_SECONDARY)
        self.screen.blit(sub, (15, 30))

        # Tick counter
        tick_text = self.font_small.render(f"Tick: {tick}", True, Colors.TEXT_DIM)
        self.screen.blit(tick_text, (self.grid_area_width - 120, 10))

        # Paused indicator
        if paused:
            pause_text = self.font_heading.render("PAUSED", True, Colors.TEXT_ORANGE)
            self.screen.blit(pause_text, (self.grid_area_width - 120, 28))

        # Quick metrics
        orders_text = self.font_tiny.render(
            f"Completed: {metrics.get('completed_orders', 0)}  "
            f"Pending: {metrics.get('pending_orders', 0)}  "
            f"Replans: {metrics.get('total_replans', 0)}  "
            f"Collisions: {metrics.get('collisions', 0)}",
            True, Colors.TEXT_DIM
        )
        self.screen.blit(orders_text, (self.grid_area_width - 430, 28))

    # ════════════════════════════════════════════════════════
    # BUTTONS
    # ════════════════════════════════════════════════════════

    def _draw_buttons(self):
        """Draw quick-action buttons."""
        mouse_pos = pygame.mouse.get_pos()
        for btn in self.buttons:
            rect = btn['rect']
            color = btn['color']
            hover = rect.collidepoint(mouse_pos)

            if hover:
                color = Colors.BTN_HOVER

            pygame.draw.rect(self.screen, color, rect, border_radius=4)
            pygame.draw.rect(self.screen, Colors.BORDER, rect, 1, border_radius=4)

            text = self.font_tiny.render(btn['label'], True, Colors.BTN_TEXT)
            text_rect = text.get_rect(center=rect.center)
            self.screen.blit(text, text_rect)

    # ════════════════════════════════════════════════════════
    # RIGHT PANEL
    # ════════════════════════════════════════════════════════

    def _draw_panel(self, terminal_lines, messages, events,
                    robot_statuses, metrics, command_input,
                    input_active, explanation_lines):
        """Draw the right-side information panel."""
        px = self.panel_x
        pw = self.panel_width

        # Panel background
        panel_rect = pygame.Rect(px, 0, pw, self.height)
        pygame.draw.rect(self.screen, Colors.BG_PANEL, panel_rect)

        # Panel title
        title_rect = pygame.Rect(px, 0, pw, 40)
        pygame.draw.rect(self.screen, Colors.BG_CARD, title_rect)
        title = self.font_heading.render("FLEET COMMAND TERMINAL", True, Colors.TEXT_ACCENT)
        self.screen.blit(title, (px + 12, 12))

        # Time
        time_str = datetime.now().strftime("%H:%M:%S")
        time_text = self.font_tiny.render(time_str, True, Colors.TEXT_DIM)
        self.screen.blit(time_text, (px + pw - 70, 15))

        pygame.draw.line(self.screen, Colors.BORDER, (px, 40), (px + pw, 40), 1)

        # ── SECTION 1: SYSTEM STATUS (compact robot list) ──
        y = 46
        y = self._draw_section_header(px, y, pw, "SYSTEM STATUS")

        for rid, status in robot_statuses.items():
            if y > 170:
                break
            color = self._status_color(status['status'])
            line = f" {status['id']} {status['status']:12s} Bat:{status['battery']:>4s}  Task:{status['task']}"
            text = self.font_tiny.render(line, True, color)
            self.screen.blit(text, (px + 8, y))
            y += 14

        # ── SECTION 2: AGENT COMMUNICATION ──
        y += 6
        y = self._draw_section_header(px, y, pw, "AGENT COMMUNICATION")

        msg_start_y = y
        msg_max_y = y + 150
        if messages:
            for msg in messages[-12:]:
                if y >= msg_max_y:
                    break
                sender_color = Colors.TEXT_CYAN if 'Coordinator' in msg.sender else Colors.TEXT_GREEN
                ts = msg.timestamp or datetime.now().strftime("%H:%M:%S")
                header = f"[{ts}] {msg.sender} → {msg.receiver}:"
                header_surf = self.font_tiny.render(header, True, sender_color)
                self.screen.blit(header_surf, (px + 8, y))
                y += 12

                # Wrap content
                content_lines = self._wrap_text(msg.content, pw - 30)
                for cl in content_lines:
                    if y >= msg_max_y:
                        break
                    content_surf = self.font_tiny.render(f"  {cl}", True, Colors.TEXT_SECONDARY)
                    self.screen.blit(content_surf, (px + 8, y))
                    y += 11
                y += 2

        # ── SECTION 3: DECISION / EXPLANATION ──
        y = max(y, msg_max_y) + 4
        y = self._draw_section_header(px, y, pw, "DECISION ANALYSIS")

        explain_max_y = y + 160
        if explanation_lines:
            for line in explanation_lines[-20:]:
                if y >= explain_max_y:
                    break
                color = Colors.TEXT_PRIMARY
                if line.startswith("["):
                    color = Colors.TEXT_ACCENT
                elif line.startswith("  "):
                    color = Colors.TEXT_SECONDARY
                if "ERROR" in line:
                    color = Colors.TEXT_RED
                if "DECISION" in line:
                    color = Colors.TEXT_GREEN
                if "SAFETY" in line:
                    color = Colors.TEXT_ORANGE

                text = self.font_tiny.render(line[:65], True, color)
                self.screen.blit(text, (px + 8, y))
                y += 12

        # ── SECTION 4: TERMINAL LOG ──
        y = max(y, explain_max_y) + 4
        y = self._draw_section_header(px, y, pw, "TERMINAL LOG")

        log_max_y = self.height - 100
        if terminal_lines:
            visible_lines = terminal_lines[-(max(1, (log_max_y - y) // 12)):]
            for line in visible_lines:
                if y >= log_max_y:
                    break
                color = Colors.TEXT_DIM
                if line.startswith(">"):
                    color = Colors.TEXT_ACCENT
                elif line.startswith("["):
                    color = Colors.TEXT_GREEN
                elif line.startswith("═"):
                    color = Colors.TEXT_ACCENT

                text = self.font_tiny.render(line[:65], True, color)
                self.screen.blit(text, (px + 8, y))
                y += 12

        # ── SECTION 5: EVENT LOG (bottom strip) ──
        event_y = self.height - 90
        pygame.draw.line(self.screen, Colors.BORDER_DIM,
                         (px + 8, event_y), (px + pw - 8, event_y), 1)
        event_title = self.font_tiny.render("EVENT LOG", True, Colors.TEXT_DIM)
        self.screen.blit(event_title, (px + 10, event_y + 3))
        ey = event_y + 16
        if events:
            for ev in events[-3:]:
                text = self.font_tiny.render(ev[:60], True, Colors.TEXT_ORANGE)
                self.screen.blit(text, (px + 10, ey))
                ey += 12

        # ── COMMAND INPUT BAR ──
        cmd_rect = self._command_bar_rect
        border_color = Colors.BORDER_ACCENT if input_active else Colors.BORDER
        pygame.draw.rect(self.screen, Colors.BG_INPUT, cmd_rect, border_radius=4)
        pygame.draw.rect(self.screen, border_color, cmd_rect, 2, border_radius=4)

        prompt = "> " + command_input
        if input_active and self.anim_tick % 30 < 15:
            prompt += "│"
        prompt_surf = self.font_input.render(prompt, True, Colors.TEXT_PRIMARY)
        self.screen.blit(prompt_surf, (cmd_rect.x + 8, cmd_rect.y + 7))

        if not input_active and not command_input:
            hint = self.font_tiny.render("Click here or press Enter to type a command...", True, Colors.TEXT_DIM)
            self.screen.blit(hint, (cmd_rect.x + 28, cmd_rect.y + 10))

    def _draw_section_header(self, px, y, pw, title) -> int:
        """Draw a section header line. Returns new y position."""
        pygame.draw.line(self.screen, Colors.BORDER_DIM,
                         (px + 8, y), (px + pw - 8, y), 1)
        y += 4
        header = self.font_small.render(title, True, Colors.TEXT_ACCENT)
        self.screen.blit(header, (px + 10, y))
        y += 18
        return y

    def _status_color(self, status_str: str) -> Tuple[int, int, int]:
        """Get color for a robot status string."""
        status_colors = {
            'MOVING': Colors.TEXT_GREEN,
            'IDLE': Colors.TEXT_SECONDARY,
            'WAITING': Colors.TEXT_ORANGE,
            'REROUTING': Colors.TEXT_ORANGE,
            'CHARGING': Colors.TEXT_CYAN,
            'LOW_BATTERY': Colors.TEXT_RED,
            'FAILED': Colors.TEXT_RED,
            'STOPPED': Colors.TEXT_RED,
            'PICKING': Colors.TEXT_PURPLE,
            'DELIVERING': Colors.TEXT_PURPLE,
        }
        return status_colors.get(status_str, Colors.TEXT_DIM)

    def _wrap_text(self, text: str, max_width: int) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        char_width = 7  # approx for monospace
        max_chars = max(20, max_width // char_width)
        lines = []
        while len(text) > max_chars:
            split = text[:max_chars].rfind(' ')
            if split <= 0:
                split = max_chars
            lines.append(text[:split])
            text = text[split:].lstrip()
        if text:
            lines.append(text)
        return lines
