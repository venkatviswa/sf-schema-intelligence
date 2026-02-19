"""Shared pytest fixtures for schema intelligence tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.data.schema_cache import load_snapshot

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_V1_DIR = FIXTURES_DIR / "snapshot_v1"
SNAPSHOT_V2_DIR = FIXTURES_DIR / "snapshot_v2"


@pytest.fixture
def snapshot_v1() -> dict:
    return load_snapshot(SNAPSHOT_V1_DIR)


@pytest.fixture
def snapshot_v2() -> dict:
    return load_snapshot(SNAPSHOT_V2_DIR)


@pytest.fixture
def v1_dir() -> Path:
    return SNAPSHOT_V1_DIR


@pytest.fixture
def v2_dir() -> Path:
    return SNAPSHOT_V2_DIR
