"""Compatibility import for the installed shared Messages API runtime.

Install the harness runtime extra; generated apps never carry their own loop.
"""
from shreyah_harness.runtime import Budget, StopRun, Tool, run_agent
