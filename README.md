# THE WAREHOUSE THAT REROUTES ITSELF

**Multi-Agent Robot Fleet Coordination Under Dynamic Disruptions**

A Python + Pygame interactive simulation demonstrating multi-agent AI concepts in a warehouse environment. Autonomous robot agents perform tasks, and users can trigger disruptions to observe intelligent decision-making, coordination, and dynamic replanning.

## Quick Start

```bash
pip install pygame PyYAML
python main.py
```

## Controls

| Action | Key/Click |
|--------|-----------|
| Activate command input | `Enter` or click command bar |
| Pause/Resume | `Space` |
| Exit | `Escape` |
| Quick actions | Click buttons below warehouse |

## Commands

| Command | Description |
|---------|-------------|
| `BLOCK A3` | Block an aisle |
| `UNBLOCK A3` | Unblock an aisle |
| `LOW BATTERY R3` | Simulate low battery |
| `RESTORE BATTERY R3` | Restore battery |
| `ROBOT FAILURE R2` | Simulate robot failure |
| `RESTORE ROBOT R2` | Restore failed robot |
| `FAIL R2` | Alias for `ROBOT FAILURE R2` |
| `RECOVER R2` | Alias for `RESTORE ROBOT R2` (only valid while R2 is FAILED) |
| `HUMAN ENTER A2` | Human enters aisle |
| `HUMAN EXIT A2` | Human exits aisle |
| `HUMAN REMOVE A2` / `REMOVE HUMAN A2` | Alias for `HUMAN EXIT A2` |
| `URGENT ORDER` | Add high-priority order |
| `ORDER SURGE` | Flash sale simulation |
| `STATUS` | Show system status |
| `HELP` | Show available commands |
| `TERMINATE` | End simulation |

## Project Architecture

```
warehouse-ai/
├── main.py                    # Entry point
├── config/                    # YAML configuration
│   ├── settings.yaml          # Simulation parameters
│   ├── warehouse.yaml         # Warehouse layout
│   ├── robots.yaml            # Robot definitions
│   └── orders.yaml            # Initial orders
├── environment/               # Warehouse grid
│   └── warehouse.py           # Grid, aisles, obstacles
├── agents/                    # Autonomous agents
│   ├── robot.py               # Robot agent
│   └── coordinator.py         # Fleet coordinator
├── models/                    # Data models
│   └── types.py               # Enums, dataclasses
├── search/                    # Search algorithms
│   └── astar.py               # A* pathfinding
├── planning/                  # Multi-agent planning
│   └── reservation.py         # Reservation table
├── simulation/                # Simulation engine
│   └── engine.py              # Main loop
├── visualization/             # Pygame rendering
│   └── renderer.py            # UI drawing
└── metrics/                   # Performance tracking
    └── collector.py           # Metrics computation
```

## AI Concepts Demonstrated

- **Intelligent Agents** (PEAS framework)
- **Multi-Agent Coordination** (fleet management)
- **A\* Search** (heuristic path planning)
- **Dynamic Replanning** (disruption response)
- **Task Allocation** (cost-based assignment)
- **Collision Avoidance** (reservation table)
- **Priority Management** (with aging)
- **Safety Constraints** (human zones)

## Team Members

*Add your team members here*

## License

Academic project – not for commercial use.
