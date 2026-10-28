import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.pipeline import build

@pytest.fixture(scope="session")
def built():
    """(cfg, sim, tables, backtest) at starter scale - built once per test session."""
    return build("starter")
