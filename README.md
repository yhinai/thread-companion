# Thread Companion

An Obsidian companion that carries your goals into coding-agent work, runs experiments, and retains evidence-backed review procedures.

**[Product and architecture](docs/PRODUCT.md)** · **[Learning proof and judging demo](docs/DEMO.md)** · **[Implementation contributions](docs/CONTRIBUTIONS.md)**

This is a first local implementation. Codex is the first adapter; Claude Code is planned. Atlas ping/read/write and a real Codex implementation/check/review/learning run have passed. All 24 automated tests pass, including localhost integration. Obsidian is installed and the plugin is configured in the proof vault; visual UI validation remains incomplete. The automated tests use a clearly identified deterministic agent double; live proof results are recorded separately.

The live learning task improved from **11/16 to 16/16** fixed checks. The 18 fresh-session transfer trials passed **6/6 in every condition**, so this fixture did **not** demonstrate an incremental procedural-memory benefit. See the [measured transfer report](docs/evidence/transfer-report.md) and [structured proof evidence](docs/evidence/proof-results.json).

Watch the [one-minute narrated evidence replay](docs/evidence/thread-demo.mp4), with [captions](docs/evidence/thread-demo.vtt). It shows the recorded results; Obsidian visual testing remains incomplete.

## Start locally

Requires Python 3.9+, Git, Obsidian desktop, and an installed/authenticated Codex CLI. No Node build step is needed for the plugin.

Check local prerequisites with `python3 -m companion.doctor`. For the private Atlas configuration, use `bash scripts/atlas.sh doctor`. These checks detect setup readiness; they do not certify model execution or Obsidian UI behavior.

```sh
python3 -m companion.server --state-dir .thread
```

The service binds only to `127.0.0.1:47123`. Copy the token from `.thread/token` into the plugin's settings. Never put it in a shared note. The coordinator must keep running while background work executes.

## Create the demo

```sh
python3 scripts/setup_demo.py
python3 scripts/install_plugin.py .thread/demo/vault
```

Open `.thread/demo/vault` in Obsidian, enable Thread Companion in Community plugins, and enter the coordinator token in its settings. Connect the repository path printed by `setup_demo.py`. The sample goal is to normalize completed-task state consistently. Use the verification command:

```json
["python3", "-m", "unittest", "discover", "-v"]
```

The fixture's basic regression checks do not establish the full task-state requirement or causal transfer. Use the learning proof in `docs/DEMO.md` for fixed acceptance checks and fresh-session transfer comparisons.

For an existing project, install the plugin into its chosen vault and connect that repository through the same panel. Experiments require a clean committed repository. Verified changes fast-forward automatically only if the user's branch has not changed.

## Commands

- **Brief:** compile relevant notes and skills, without launching an agent.
- **Build:** execute a task with independent verification.
- **Review:** inspect work against goals and project checks.
- **Explore:** investigate alternatives and apply supported improvements.
- **Keep refining while I'm away:** explicit continuous Explore, without an application session cap. Stop from the activity panel.

The adapter requests read-only planning/review and workspace-write implementation, subject to the Codex permission profile. It does not override managed environment policies or read a sudo password from shell configuration.

## Atlas Sandbox

Install the driver in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-atlas.txt
```

Set `MONGODB_URI` to the provided hackathon Sandbox connection string and optionally `MONGODB_DATABASE=thread` in the coordinator environment. Then run the coordinator with `.venv/bin/python`. The configuration example is `.env.example`; it is not loaded automatically.

Selecting Atlas fails explicitly on connection/driver errors. There is no silent SQLite fallback. Local SQLite development does not meet the hackathon's Atlas eligibility requirement.

For a private shell-format `.env` file, the helper loads it for these commands:

```sh
bash scripts/atlas.sh check
bash scripts/atlas.sh doctor
bash scripts/atlas.sh proof prepare --root .thread/atlas-proof
bash scripts/atlas.sh server --state-dir .thread/atlas-proof/runtime
```

`check` verifies ping plus a small read/write round trip and stores a credential-free report in `.thread/atlas-connection.json`. It retains a diagnostic record in the `connection_checks` collection. The helper requires the virtual environment and MongoDB driver above. `.env` is Git-ignored; keep its permissions restricted to your account.


## Tests

```sh
PYTHONPYCACHEPREFIX=.thread/pycache python3 -m unittest discover -s tests -v
```

Live HTTP integration tests require permission to bind localhost and skip when the host disallows it. Additional tests exercise the actual request handler in memory without opening sockets. Test doubles are confined to `tests/`; application runs use Codex.

## Layout

- `companion/`: coordinator, memory, storage, Git, and Codex adapter.
- `plugin/`: ready-to-load Obsidian plugin.
- `examples/`: sample notes and a deliberately imperfect repository fixture.
- `scripts/`: demo setup and plugin installation.
- `tests/`: lifecycle, retrieval, promotion, cancellation, and API checks.

See the [product overview](docs/PRODUCT.md) for current limitations, including incomplete semantic retrieval, exact-step recovery, dependent-task scheduling, optional auto-review wiring, and live event streaming.
