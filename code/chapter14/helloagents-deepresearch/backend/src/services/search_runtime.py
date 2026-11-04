"""Cooperative guards around the existing shared SearchTool dispatch."""
from services.execution_control import checkpoint


def run_search(dispatch, *args):
    checkpoint()
    result = dispatch(*args)
    checkpoint()
    return result
