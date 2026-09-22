"""
THE WAREHOUSE THAT REROUTES ITSELF
Multi-Agent Robot Fleet Coordination Under Dynamic Disruptions

Main entry point – launches the Pygame simulation.

Usage:
    python main.py

Controls:
    Enter/Return : Activate command input
    Space        : Pause/Resume simulation
    Escape       : Exit
    Click buttons: Trigger quick actions
    Type commands: BLOCK A3, LOW BATTERY R3, HELP, STATUS, etc.
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulation.engine import SimulationEngine


def main():
    """Launch the warehouse simulation."""
    engine = SimulationEngine()
    engine.run()


if __name__ == "__main__":
    main()
