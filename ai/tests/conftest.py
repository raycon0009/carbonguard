import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from helpers import run_pipeline  # noqa: E402


@pytest.fixture(scope="session")
def run(tmp_path_factory):
    """One full generate -> train -> score run, shared by every test file."""
    return run_pipeline(tmp_path_factory.mktemp("run1"))
