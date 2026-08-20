"""Pytest configuration for RLTech FTTR tests."""

from __future__ import annotations

import asyncio
import sys

import pytest


@pytest.fixture
def event_loop_policy(socket_enabled):
    """Use a Windows event loop policy that works with pytest-socket."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()
