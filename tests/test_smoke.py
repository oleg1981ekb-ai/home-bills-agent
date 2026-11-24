"""Smoke tests for home-bills-agent."""

import sys


def test_python_version():
    """Python 3.11+ required."""
    assert sys.version_info >= (3, 11)
