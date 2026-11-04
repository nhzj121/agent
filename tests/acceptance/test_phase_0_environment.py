"""G0 acceptance: real isolated build/install; Fake runtime; temporary filesystem probes.

Run with a Python 3.12 base interpreter:
    python -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v

No original .venv packages, existing notes, .env files, or production API are used.
The known G1 research defects are deliberately not repaired or hidden by these tests.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "code/chapter14/helloagents-deepresearch/backend"
EXPECTED_MODULES = ("agent", "config", "main", "models", "prompts", "utils")
EXPECTED_SERVICES = ("__init__", "notes", "planner", "reporter", "search",
                     "summarizer", "text_processing", "tool_events", "agent_adapter",
                     "note_versions", "note_ownership", "execution_control", "search_runtime", "sse_bridge", "notes_runtime")
EXPECTED_STORAGE = ("__init__", "note_repository", "file_notes", "note_codec", "manual_edit")
CONTEXT = None


def identity_facts():
    """Distribution registration name and OS version are independent facts."""
    try:
        os_release = platform.freedesktop_os_release()
    except OSError:
        os_release = {}
    return {
        "system": platform.system(), "kernel": platform.release(),
        "wsl_registered_name": os.environ.get("WSL_DISTRO_NAME"),
        "os_id": os_release.get("ID"), "os_version_id": os_release.get("VERSION_ID"),
        "python": platform.python_version(),
    }


def require_capabilities(identity, capabilities):
    if identity["system"] != "Linux":
        raise RuntimeError("G0 requires Linux filesystem semantics")
    missing = [name for name in ("flock", "dir_fd", "nofollow", "atomic_replace",
                                 "directory_fsync") if not capabilities.get(name)]
    if missing:
        raise RuntimeError("Missing filesystem capabilities: " + ", ".join(missing))


def process_environment(extra=None):
    # Runtime is intentionally separate from inherited model/search/notes settings.
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
        "ENABLE_NOTES": "false", "LLM_PROVIDER": "ollama",
        "LOCAL_LLM": "g0-fake", "SEARCH_API": "duckduckgo",
        "NO_PROXY": "127.0.0.1,localhost,::1",
    }
    for name in ("SYSTEMROOT", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    if extra:
        env.update(extra)
    return env


# Included in every application runtime child, before importing third-party code.
# Package download/build subprocesses do NOT use this guard.
RUNTIME_GUARD = r"""
import os, socket, pathlib, sys
from unittest.mock import patch
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo
def _local_host(host):
    return host in (None, "localhost", "127.0.0.1", "::1")
def _guard_connect(self, address):
    if self.family == socket.AF_UNIX:
        return _original_connect(self, address)
    if not isinstance(address, tuple) or not _local_host(address[0]):
        raise AssertionError("G0 runtime forbids external network connections")
    return _original_connect(self, address)
def _guard_connect_ex(self, address):
    if self.family == socket.AF_UNIX:
        return _original_connect_ex(self, address)
    if not isinstance(address, tuple) or not _local_host(address[0]):
        raise AssertionError("G0 runtime forbids external network connections")
    return _original_connect_ex(self, address)
def _guard_getaddrinfo(host, *args, **kwargs):
    if not _local_host(host):
        raise AssertionError("G0 runtime forbids external DNS lookup")
    return _original_getaddrinfo(host, *args, **kwargs)
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
socket.getaddrinfo = _guard_getaddrinfo
"""


class RunContext:
    def __init__(self):
        os.chdir(ROOT)
        actual = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                         text=True).strip()
        if actual != str(ROOT):
            raise RuntimeError("Unexpected repository root")
        if sys.version_info < (3, 11):
            raise RuntimeError("G0 acceptance controller requires Python 3.11+ (verified: 3.12)")
        parent = ROOT / "venv"
        parent.mkdir(exist_ok=True)
        supplied = os.environ.get("G0_WORK_ROOT")
        if supplied:
            self.work = Path(supplied).resolve()
            if not self.work.is_relative_to(parent.resolve()) or self.work == parent.resolve():
                raise RuntimeError("G0_WORK_ROOT must be a new directory under ignored repository venv/")
            if self.work.exists() and any(self.work.iterdir()):
                raise RuntimeError("Refusing to reuse a nonempty G0 environment")
            self.work.mkdir(parents=True, exist_ok=True)
        else:
            self.work = Path(tempfile.mkdtemp(prefix="g0-", dir=parent))
        self.logs = self.work / "logs"
        self.logs.mkdir()
        self.commands = []
        self.capabilities = {}
        self.base_python = str(Path(os.environ.get("G0_BASE_PYTHON",
                                                   sys._base_executable)).resolve())
        self.uv = os.environ.get("G0_UV") or shutil.which("uv")
        if not self.uv:
            candidate = Path.home() / ".local/bin/uv"
            if candidate.is_file():
                self.uv = str(candidate)
        if not self.uv:
            raise RuntimeError("uv unavailable; do not install automatically")
        self.runtime = self.work / "runtime"
        self.source = self.work / "source"
        self.artifacts = self.work / "artifacts"
        self.cwd = self.work / "unrelated-working-directory"
        self.cwd.mkdir()
        self.notes_sentinel = self.work / "notes-must-not-be-created"
        self.runtime_env = process_environment({"NOTES_WORKSPACE": str(self.notes_sentinel)})
        # Snapshot the current authorized revision, not the immutable G0-era code.
        # The historical manifest still defines protected paths; its saved hashes
        # remain evidence, not a ban on subsequent approved source changes.
        baseline = json.loads((ROOT / "docs/g0_evidence/baseline.json").read_text())
        self.original_fingerprints = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in baseline["files"]
        }
        self.write_json("identity.json", identity_facts())
        print("G0_WORK_ROOT=" + str(self.work), flush=True)

    def write_json(self, name, value):
        (self.work / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    def command(self, label, args, *, cwd=None, env=None, timeout=180):
        record = {"label": label, "argv": list(map(str, args)),
                  "cwd": str(cwd or self.work)}
        self.commands.append(record)
        self.write_json("commands.json", self.commands)
        result = subprocess.run(args, cwd=cwd or self.work, env=env,
                                capture_output=True, text=True, timeout=timeout)
        (self.logs / (label + ".stdout.txt")).write_text(result.stdout, encoding="utf-8")
        (self.logs / (label + ".stderr.txt")).write_text(result.stderr, encoding="utf-8")
        record["exit_code"] = result.returncode
        self.write_json("commands.json", self.commands)
        if result.returncode:
            raise RuntimeError(
                f"{label} failed ({result.returncode}); see {self.logs}\n"
                + result.stdout[-2000:] + result.stderr[-5000:])
        return result

    def child(self, label, code):
        result = self.command(
            label, [str(self.runtime / "bin/python"), "-I", "-B", "-c",
                    RUNTIME_GUARD + "\n" + code],
            cwd=self.cwd, env=self.runtime_env, timeout=40)
        if self.notes_sentinel.exists():
            raise AssertionError("Runtime unexpectedly created a notes workspace")
        lines = [line for line in result.stdout.splitlines() if line.startswith("G0_JSON=")]
        if not lines:
            raise AssertionError(f"{label}: missing result: {result.stdout[-2000:]}")
        return json.loads(lines[-1][8:])

    def bootstrap(self):
        self.source.mkdir()
        for name in ("pyproject.toml", "uv.lock", "README.md"):
            shutil.copyfile(BACKEND / name, self.source / name)
        shutil.copytree(BACKEND / "src", self.source / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "*.pyc",
                                                     ".env", ".env.*", ".venv", "venv", "notes"))
        self.artifacts.mkdir()
        build_env = {**os.environ, "UV_NO_PROGRESS": "1",
                     "UV_PYTHON_DOWNLOADS": "never",
                     "UV_PROJECT_ENVIRONMENT": str(self.work / "unused-project-env")}
        # Metadata, lock checks and builds run only in a source copy.
        self.command("lock-check", [self.uv, "lock", "--project", str(self.source),
                     "--python", self.base_python, "--check", "--offline"], env=build_env)
        self.command("build", [self.uv, "build", "--project", str(self.source),
                     "--python", self.base_python, "--out-dir", str(self.artifacts)],
                     env=build_env)
        wheels = list(self.artifacts.glob("*.whl"))
        sdists = list(self.artifacts.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("Expected one wheel and one sdist")
        self.wheel, self.sdist = wheels[0], sdists[0]
        self.command("create-runtime", [self.uv, "venv", "--python",
                     self.base_python, str(self.runtime)], env=build_env)
        empty = self.command("empty-runtime", [
            str(self.runtime / "bin/python"), "-I", "-B", "-c",
            "import importlib.metadata as m,json,sys;print(json.dumps("
            "{'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
            "'distributions':[d.metadata['Name'] for d in m.distributions()]}))"],
            env=self.runtime_env)
        self.empty_environment = json.loads(empty.stdout)
        if self.empty_environment["distributions"]:
            raise RuntimeError("New runtime is not empty before dependency installation")
        self.requirements = self.work / "runtime-requirements.txt"
        self.command("export-lock", [self.uv, "export", "--project",
                     str(self.source), "--locked", "--no-dev", "--no-emit-project",
                     "--format", "requirements-txt", "--output-file",
                     str(self.requirements)], env=build_env)
        self.command("install-runtime-dependencies", [self.uv, "pip", "install",
                     "--python", str(self.runtime / "bin/python"), "--require-hashes",
                     "--no-deps", "-r", str(self.requirements)], env=build_env)
        self.command("install-wheel", [self.uv, "pip", "install", "--python",
                     str(self.runtime / "bin/python"), "--no-deps", str(self.wheel)],
                     env=build_env)
        self.command("dependency-check", [self.uv, "pip", "check", "--python",
                     str(self.runtime / "bin/python")], env=build_env)
        self.write_json("setup.json", {
            "base_python": self.base_python, "uv": self.uv,
            "runtime": str(self.runtime), "source_copy": str(self.source),
            "wheel": str(self.wheel), "sdist": str(self.sdist),
            "empty_environment": self.empty_environment,
            "wheel_sha256": hashlib.sha256(self.wheel.read_bytes()).hexdigest(),
            "lock_sha256": hashlib.sha256((BACKEND / "uv.lock").read_bytes()).hexdigest(),
            "pyproject_sha256": hashlib.sha256((BACKEND / "pyproject.toml").read_bytes()).hexdigest(),
        })

    def server_health(self, label, *, app_dir=None, source_cwd=False):
        server_cwd = self.source / "src" if source_cwd else self.cwd
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        guard = RUNTIME_GUARD + r"""
import hello_agents
from hello_agents.tools import SearchTool
from hello_agents.tools.builtin.note_tool import NoteTool
def _forbidden(*args, **kwargs):
    raise AssertionError("Real LLM/search/notes forbidden in G0 health startup")
hello_agents.HelloAgentsLLM.__init__ = _forbidden
SearchTool.run = _forbidden
NoteTool.__init__ = _forbidden
import runpy
sys.argv = ["uvicorn"] + sys.argv[1:]
runpy.run_module("uvicorn", run_name="__main__")
"""
        args = [str(self.runtime / "bin/python"), "-I", "-B", "-c", guard,
                "main:app", "--host", "127.0.0.1", "--port", str(port),
                "--log-level", "warning"]
        if app_dir:
            args += ["--app-dir", str(app_dir)]
        record = {"label": label, "argv": args, "cwd": str(server_cwd)}
        self.commands.append(record)
        self.write_json("commands.json", self.commands)
        logfile = self.logs / (label + ".txt")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with logfile.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(args, cwd=server_cwd, env=self.runtime_env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError(f"{label} exited {process.returncode}: {logfile.read_text()[-3000:]}")
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=0.5) as response:
                            body = json.loads(response.read())
                            if response.status == 200:
                                if body != {"status": "ok"}:
                                    raise AssertionError(body)
                                record["health_status"] = 200
                                return body
                    except (urllib.error.URLError, TimeoutError, ConnectionError):
                        time.sleep(0.1)
                raise AssertionError(f"{label} health timeout: {logfile.read_text()[-3000:]}")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                record["exit_after_owned_process_termination"] = process.returncode
                self.write_json("commands.json", self.commands)
                if self.notes_sentinel.exists():
                    raise AssertionError("Health startup created notes")


def context():
    global CONTEXT
    if CONTEXT is None:
        CONTEXT = RunContext()
    return CONTEXT


class G0FilesystemTests(unittest.TestCase):
    def test_01_registration_name_is_not_os_version(self):
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "research-dev"}), \
             patch("platform.freedesktop_os_release",
                   return_value={"ID": "ubuntu", "VERSION_ID": "22.04"}):
            facts = identity_facts()
        self.assertEqual(facts["wsl_registered_name"], "research-dev")
        self.assertEqual(facts["os_version_id"], "22.04")
        require_capabilities(facts, dict.fromkeys(
            ("flock", "dir_fd", "nofollow", "atomic_replace", "directory_fsync"), True))
        facts["wsl_registered_name"] = "Ubuntu22.04.3"
        with self.assertRaisesRegex(RuntimeError, "directory_fsync"):
            require_capabilities(facts, {"flock": True, "dir_fd": True,
                                       "nofollow": True, "atomic_replace": True})

    def test_02_cross_process_flock(self):
        ctx = context()
        with tempfile.TemporaryDirectory(dir=ctx.work) as directory:
            lock = Path(directory) / "lock"
            code = r"""
import fcntl,sys
with open(sys.argv[1],"a+b") as stream:
 try:
  fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
  print("acquired")
 except BlockingIOError:
  print("blocked")
"""
            with lock.open("a+b") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked = ctx.command("flock-blocked", [ctx.base_python, "-I", "-B",
                                      "-c", code, str(lock)], env=process_environment())
                self.assertEqual(blocked.stdout.strip(), "blocked")
                fcntl.flock(stream, fcntl.LOCK_UN)
            acquired = ctx.command("flock-released", [ctx.base_python, "-I", "-B",
                                   "-c", code, str(lock)], env=process_environment())
            self.assertEqual(acquired.stdout.strip(), "acquired")
        ctx.capabilities["flock"] = True

    def test_03_dir_fd_and_nofollow(self):
        ctx = context()
        self.assertIn(os.open, os.supports_dir_fd)
        self.assertTrue(hasattr(os, "O_NOFOLLOW"))
        with tempfile.TemporaryDirectory(dir=ctx.work) as directory:
            root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fd = os.open("plain", os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=root_fd)
                os.write(fd, b"fixture")
                os.close(fd)
                os.symlink("plain", Path(directory) / "link")
                with self.assertRaises(OSError) as raised:
                    os.open("link", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
                self.assertEqual(raised.exception.errno, errno.ELOOP)
                fd = os.open("plain", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
                self.assertEqual(os.read(fd, 100), b"fixture")
                os.close(fd)
            finally:
                os.close(root_fd)
        ctx.capabilities.update(dir_fd=True, nofollow=True)

    def test_04_atomic_replace_reader_sees_complete_versions(self):
        ctx = context()
        with tempfile.TemporaryDirectory(dir=ctx.work) as directory:
            directory = Path(directory)
            target = directory / "target"
            old, new = b"A" * 4096, b"B" * 8192
            target.write_bytes(old)
            stop, ready = threading.Event(), threading.Event()
            errors, observed = [], []
            def read():
                try:
                    while not stop.is_set():
                        content = target.read_bytes()
                        if content not in (old, new):
                            errors.append(len(content))
                        observed.append(len(content))
                        ready.set()
                except Exception as exc:
                    errors.append(str(exc))
                    ready.set()
            reader = threading.Thread(target=read)
            reader.start()
            try:
                self.assertTrue(ready.wait(2))
                for index in range(40):
                    pending = directory / f"pending-{index}"
                    with pending.open("xb") as output:
                        output.write(new if index % 2 == 0 else old)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(pending, target)
                self.assertIn(target.read_bytes(), (old, new))
            finally:
                stop.set()
                reader.join(3)
            self.assertFalse(reader.is_alive())
            self.assertTrue(observed)
            self.assertFalse(errors, errors)
        ctx.capabilities["atomic_replace"] = True

    def test_05_directory_fsync(self):
        ctx = context()
        with tempfile.TemporaryDirectory(dir=ctx.work) as directory:
            file = Path(directory) / "payload"
            with file.open("xb") as output:
                output.write(b"filesystem probe")
                output.flush()
                os.fsync(output.fileno())
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        ctx.capabilities["directory_fsync"] = True
        require_capabilities(identity_facts(), ctx.capabilities)
        ctx.write_json("capabilities.json", ctx.capabilities)


class G0PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = context()
        cls.ctx.bootstrap()

    def test_00_source_copy_excludes_private_artifacts_and_preserves_code(self):
        source = self.ctx.source
        self.assertFalse(any(p.name == ".env" or p.name.startswith(".env.")
                             for p in source.rglob("*")))
        self.assertFalse((source / ".venv").exists())
        self.assertFalse((source / "notes").exists())
        for original in (BACKEND / "src").rglob("*.py"):
            if "__pycache__" in original.parts:
                continue
            copied = source / "src" / original.relative_to(BACKEND / "src")
            self.assertTrue(copied.is_file(), str(copied))
            self.assertEqual(original.read_bytes(), copied.read_bytes())

    def test_01_wheel_payload_and_declared_dependencies(self):
        ctx = self.ctx
        with zipfile.ZipFile(ctx.wheel) as wheel:
            names = set(wheel.namelist())
            for module in EXPECTED_MODULES:
                self.assertIn(module + ".py", names)
            for module in EXPECTED_SERVICES:
                self.assertIn("services/" + module + ".py", names)
            for module in ("__init__", "project_note_tool", "controlled_tool"):
                self.assertIn("tools/" + module + ".py", names)
            for module in ("__init__", "project_llm"):
                self.assertIn("llm/" + module + ".py", names)
            for module in EXPECTED_STORAGE:
                self.assertIn("storage/" + module + ".py", names)
            self.assertFalse(any(name.startswith("src/src/") for name in names))
            self.assertFalse(any("/notes/" in name or name.endswith("/.env")
                                 for name in names))
            metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
            metadata = wheel.read(metadata_name).decode()
            for dependency in ("hello-agents==0.2.9", "huggingface-hub==2.3.0",
                               "PyYAML==6.0.3"):
                self.assertIn(dependency.lower(), metadata.lower())
        config = tomllib.loads((BACKEND / "pyproject.toml").read_text())
        self.assertEqual(config["build-system"]["requires"],
                         ["setuptools==84.2.1", "wheel==0.48.0"])

    def test_02_sdist_contains_readme_and_all_sources(self):
        with tarfile.open(self.ctx.sdist) as archive:
            names = archive.getnames()
        top = names[0].split("/")[0]
        self.assertIn(top + "/README.md", names)
        self.assertIn(top + "/pyproject.toml", names)
        for module in EXPECTED_MODULES:
            self.assertIn(top + "/src/" + module + ".py", names)
        for module in EXPECTED_SERVICES:
            self.assertIn(top + "/src/services/" + module + ".py", names)
        for module in ("__init__", "project_note_tool", "controlled_tool"):
            self.assertIn(top + "/src/tools/" + module + ".py", names)
        for module in ("__init__", "project_llm"):
            self.assertIn(top + "/src/llm/" + module + ".py", names)
        for module in EXPECTED_STORAGE:
            self.assertIn(top + "/src/storage/" + module + ".py", names)
        self.assertFalse(any(name.endswith("/.env") or "/notes/" in name for name in names))

    def test_03_installed_imports_are_source_independent(self):
        result = self.ctx.child("installed-imports", r"""
import importlib,importlib.metadata as m,json,sys,pathlib
names=["main","agent","config","models","prompts","utils","services.planner",
       "services.search","services.summarizer","services.reporter",
       "services.notes","services.text_processing","services.tool_events",
       "llm.project_llm","tools.controlled_tool","services.execution_control","services.search_runtime","services.sse_bridge","services.notes_runtime",
       "tools.project_note_tool","services.agent_adapter","services.note_versions","services.note_ownership",
       "storage.note_repository","storage.file_notes","storage.note_codec","storage.manual_edit",
       "hello_agents","huggingface_hub","yaml"]
locations={name:importlib.import_module(name).__file__ for name in names}
prefix=pathlib.Path(sys.prefix)
assert all(pathlib.Path(path).is_relative_to(prefix) for path in locations.values()),locations
print("G0_JSON="+json.dumps({"prefix":sys.prefix,"base_prefix":sys.base_prefix,
"sys_path":sys.path,"locations":locations,
"versions":{d.metadata["Name"]:d.version for d in m.distributions()}}))
""")
        self.assertEqual(Path(result["prefix"]), self.ctx.runtime)
        old = str(BACKEND / ".venv")
        for entry in result["sys_path"]:
            self.assertNotIn(old, entry)
            self.assertNotEqual(entry, str(BACKEND / "src"))
            self.assertNotEqual(entry, str(self.ctx.source / "src"))
        self.assertEqual(result["versions"]["hello-agents"], "0.2.9")
        self.assertEqual(result["versions"]["huggingface_hub"], "2.3.0")
        self.ctx.write_json("installed-environment.json", result)

    def test_04_installed_dependencies_match_lock(self):
        result = self.ctx.child("installed-metadata", r"""
import importlib.metadata as m,json
print("G0_JSON="+json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))
""")
        locked = tomllib.loads((BACKEND / "uv.lock").read_text())
        normalize = lambda name: name.lower().replace("_", "-").replace(".", "-")
        versions = {}
        for package in locked["package"]:
            versions.setdefault(normalize(package["name"]), set()).add(package["version"])
        for name, version in result.items():
            self.assertIn(version, versions.get(normalize(name), set()), (name, version))
        self.assertNotIn("pip", {normalize(name) for name in result})
        self.assertEqual(self.ctx.empty_environment["distributions"], [])

    def test_05_fake_http_routes_and_no_real_notes_or_llm(self):
        result = self.ctx.child("fake-http-smoke", r"""
import json
import main
from types import SimpleNamespace
from models import TodoItem
from fastapi.testclient import TestClient
from hello_agents import HelloAgentsLLM
from hello_agents.tools import SearchTool
from hello_agents.tools.builtin.note_tool import NoteTool
from loguru import logger
logger.disable("main")
def forbidden(*args,**kwargs):
 raise AssertionError("Real API/notes execution forbidden in G0")
calls=[]
class FakeCoordinator:
 def __init__(self,config): calls.append(("init",config.enable_notes))
 def run(self,topic):
  calls.append(("run",topic))
  return SimpleNamespace(report_markdown="G0 fake report",running_summary=None,
   todo_items=[TodoItem(id=1,title="fake",intent="fake",query="fake",
                       status="completed",summary="fake summary")])
 def run_stream(self,topic):
  calls.append(("stream",topic))
  yield {"type":"status","message":"fake started"}
  if topic=="fake-error": raise RuntimeError("G0 fake stage failure")
  yield {"type":"todo_list","tasks":[]}
  yield {"type":"final_report","report":"G0 fake report"}
  yield {"type":"done"}
with patch.object(main,"DeepResearchAgent",FakeCoordinator), \
 patch.object(HelloAgentsLLM,"__init__",forbidden), \
 patch.object(SearchTool,"run",forbidden), \
 patch.object(NoteTool,"__init__",forbidden):
 with TestClient(main.app) as client:
  health=client.get("/healthz")
  sync=client.post("/research",json={"topic":"fake"})
  stream=client.post("/research/stream",json={"topic":"fake"})
  error=client.post("/research/stream",json={"topic":"fake-error"})
assert health.status_code==200 and health.json()=={"status":"ok"}
assert sync.status_code==200 and sync.json()["report_markdown"]=="G0 fake report"
frames=lambda response:[json.loads(frame[6:]) for frame in response.text.strip().split("\n\n")]
assert [e["type"] for e in frames(stream)]==["status","todo_list","final_report","done"]
assert stream.headers["content-type"].startswith("text/event-stream")
assert error.status_code==200 and frames(error)[-1]["type"]=="error"
assert all(not item[1] for item in calls if item[0]=="init")
assert not pathlib.Path(os.environ["NOTES_WORKSPACE"]).exists()
print("G0_JSON="+json.dumps({"health":200,"research":200,
"stream_types":[e["type"] for e in frames(stream)],"error_type":"error","calls":calls}))
""")
        self.assertEqual(result["research"], 200)
        self.ctx.write_json("http-smoke.json", result)

    def test_06_installed_uvicorn_starts_without_source_pythonpath(self):
        self.assertEqual(self.ctx.server_health("startup-installed"), {"status": "ok"})

    def test_07_existing_app_dir_startup_is_compatible(self):
        self.assertEqual(self.ctx.server_health(
            "startup-app-dir", app_dir=self.ctx.source / "src"), {"status": "ok"})

    def test_08_existing_src_working_directory_is_compatible(self):
        self.assertEqual(self.ctx.server_health(
            "startup-src-cwd", source_cwd=True), {"status": "ok"})

    def test_09_no_original_files_or_environment_are_rewritten(self):
        changed = []
        for name, digest in self.ctx.original_fingerprints.items():
            file = ROOT / name
            actual = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None
            if actual != digest:
                changed.append(name)
        self.assertEqual(changed, [])
        self.assertFalse(self.ctx.notes_sentinel.exists())
        self.assertIn("include-system-site-packages = false",
                      (self.ctx.runtime / "pyvenv.cfg").read_text().lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
