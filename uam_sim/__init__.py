"""
UAM Corridor Communication-Transportation Simulator

A graph-based simulation model that jointly captures UAM corridor traffic
dynamics, communication network behavior, and mode switching between
HOTL and HWTL operation modes.
"""

from uam_sim.config import default_config, validate_config
from uam_sim.engine import run_simulation
from uam_sim.report import generate_html_report

__all__ = ["run_simulation", "generate_html_report", "default_config", "validate_config"]
__version__ = "0.1.0"
