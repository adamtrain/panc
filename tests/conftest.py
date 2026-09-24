import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def sample():
    """Load any fixture by name."""
    return load


@pytest.fixture
def mixed() -> dict:
    return load("mixed")


@pytest.fixture
def docs_example() -> dict:
    return load("docs_example")
