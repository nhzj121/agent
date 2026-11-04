# HelloAgents DeepResearch backend

## Environment baseline

G0 keeps the existing flat Python modules and the `services` package. It fixes
packaging and declares the dependencies needed by ordinary imports; it does not
change the research workflow. The current verified runtime is CPython 3.12 on
single-host WSL2/Linux. `requires-python >=3.10` remains the inherited package
range; other Python versions require their own runtime validation.

- Runtime versions are resolved in `uv.lock`; use `--locked` when installing.
- `hello-agents==0.2.9` remains unchanged. Its eager evaluation imports require
  `huggingface-hub` even though this application does not use evaluation extras.
- PyYAML is a direct dependency for the planned codec; G0 does not implement it.
- Build backend versions are pinned in `[build-system]` so the isolated build
  does not silently select a different backend.
- The G0 acceptance suite uses standard-library `unittest`; it provisions its
  own clean environment and does not rely on packages in `backend/.venv`.

WSL's registered distribution name (for example `Ubuntu22.04.3`) is an identifier,
not the Ubuntu `VERSION_ID`. Record it separately from `/etc/os-release`.
G0 tests Linux filesystem capabilities in temporary directories.

## Install into a new environment

The following commands are for a **new environment**, not the existing
`backend/.venv`. From this backend directory, choose a new environment path:

```bash
G0_NEW_ENV=/absolute/path/to/a/new/environment
UV_PROJECT_ENVIRONMENT="$G0_NEW_ENV" uv sync --locked --no-dev --python 3.12
```

Do not point `G0_NEW_ENV` at the established development environment when
validating reconstruction. The checked-in lock covers runtime and dev resolution;
`--no-dev` installs the runtime subset.

## Existing startup commands

The source layout and entrypoint remain unchanged:

```bash
# From backend/:
"$G0_NEW_ENV/bin/python" -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000

# Equivalent existing source-directory form:
cd src
"$G0_NEW_ENV/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 8000
```

After a wheel is installed, `main:app` also works from an unrelated working
directory without `--app-dir` or source `PYTHONPATH`. `python src/main.py` retains
its original behavior (including reload and the original bind address); G0 does
not change that script.

Supply configuration through the environment or your established launcher.
G0 does not add automatic loading of `.env`. Do not use real model credentials
or the existing notes workspace when running acceptance tests.

## G0 acceptance

From the repository root, using a Python 3.12 base interpreter and existing uv:

```bash
export G0_BASE_PYTHON=/absolute/path/to/base/python3.12
export G0_UV=/absolute/path/to/uv
"$G0_BASE_PYTHON" -B -m unittest discover \
  -s tests/acceptance -p 'test_phase_0*.py' -v
```

The suite creates a unique ignored `venv/g0-*` directory under the repository,
builds a source copy (without `.env`, notes, or the old `.venv`), exports the
locked runtime requirements, and installs dependencies plus the built wheel into
a new environment. It retains logs and artifacts in that validation directory.
`G0_WORK_ROOT` can name an empty directory under the ignored repository `venv/`;
an existing nonempty directory is rejected.

The runtime checks block external network connections and use Fake agents.
Local loopback HTTP is used only for startup/health checks. Package resolution
and installation may download distributions from PyPI. The suite never reads,
copies, creates, or modifies the existing notes workspace.

The `/research` and `/research/stream` smoke checks verify HTTP wiring using a
Fake coordinator. They do **not** claim to fix A01 or other research correctness
defects reserved for G1 and later stages.

Acceptance output and exact commands for the completed run are recorded in
`docs/deepresearch_g0_results.md` and `docs/g0_evidence/` at repository root.
