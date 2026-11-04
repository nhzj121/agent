"""Build only a temporary fixture with already cached setuptools/wheel. No install."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
os.chdir(root)
assert os.environ.get("WSL_DISTRO_NAME") == "Ubuntu22.04.3"
assert subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip() == str(root)
backend = root / "code/chapter14/helloagents-deepresearch/backend"
cache = Path.home() / ".cache/uv/archive-v0"
setuptools = list(cache.glob("*/setuptools/__init__.py"))
wheel = list(cache.glob("*/wheel/__init__.py"))
if not setuptools or not wheel:
    raise SystemExit("BLOCKED: cached setuptools/wheel unavailable; do not install automatically")
paths = [str(p.parent.parent) for p in setuptools + wheel]
with tempfile.TemporaryDirectory(prefix="deepresearch-build-audit-") as directory:
    fixture = Path(directory) / "project"
    fixture.mkdir()
    shutil.copyfile(backend / "pyproject.toml", fixture / "pyproject.toml")
    shutil.copytree(backend / "src", fixture / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    code = (
        "import socket; from unittest.mock import patch; "
        "import setuptools; print('SETUPTOOLS',setuptools.__version__,flush=True); "
        "import setuptools.build_meta as b; "
        "guard=patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')); "
        "guard.start(); print(b.build_wheel('wheel-output'))"
    )
    result = subprocess.run(
        [str(backend / ".venv/bin/python"), "-B", "-c", code],
        cwd=fixture, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": ":".join(paths), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    print(result.stdout)
    print(result.stderr)
    print(json.dumps({"build_exit": result.returncode, "expected_current_error": "package directory 'src/src' does not exist" in result.stderr}))
    raise SystemExit(0 if result.returncode and "package directory 'src/src' does not exist" in result.stderr else 1)
