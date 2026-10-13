# sam-fx · FX operations desk

A company-neutral, dark terminal-style demo for monitoring FX price delivery. Synthetic market conditions and regional service health are shown separately. Confirmed service incidents produce a frozen evidence summary, an owner, suggested runbook checks and a handover record. No trading or remediation actions are performed.

The adaptation is based on public research into global-bank FX support workflows. See [research, rationale and production boundaries](docs/citi-operations-design.md).

## Published demo

[Open sam-fx on GitHub Pages](https://solacese.github.io/sam-fx/).

The public site is a self-contained browser demo. Python generates the scenario frames
from the same detector, service monitor and prepared explanation code during the build.
The browser replays them once per second, saves its incident journal in local storage,
and exports handover JSON. It makes no backend, broker or model requests. Timing is
explicitly labeled as replay, not a production latency measurement. Browser storage is
local to this origin/device and is not a shared or authenticated incident database.

```bash
PYTHONPATH=src .venv/bin/python scripts/build_pages.py
node scripts/test_pages.cjs
python3 -m http.server 8082 --directory dist
# Open http://localhost:8082/pages/
```

Pushes to `main` run `.github/workflows/pages.yml`: checks, static build, and Pages deployment.
Only `dist/pages` is published as the website. Backend and integration source remain in the repository.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
PYTHONPATH=src SOLACE_HOST='' ENABLE_EXTERNAL_PROVIDERS=false \
  .venv/bin/uvicorn fx_regime.api:app --host 127.0.0.1 --port 8080
```

Open <http://localhost:8080>. Default explanations and the three desk answers are deterministic; no LLM is required. `ENABLE_EXTERNAL_PROVIDERS=true` opts into configured Jev/Groq calls. Do not send private data without the appropriate approval.

## Try it

- **Market move:** a market advisory while delivery remains healthy.
- **Slow consumer:** one regional path degrades; peer evidence helps localize it.
- **Silent feed:** an incident despite normal market statistics.
- **Missing telemetry:** visibility becomes UNKNOWN, not healthy or a proven outage.
- **Market + delivery stress:** abnormal market activity and delivery impairment together.

Scenarios last twelve observations. **Restore normal** ends one early. A service incident requires three consecutive abnormal observations, recovery requires five healthy observations, and **Resolve incident** becomes available after recovery. **Acknowledge** records the demo operator action. Select an incident to see its frozen evidence and runbook. **Export handover** downloads the journal.

The two regional paths, owners, timestamps, priorities and telemetry are synthetic. The chart is a synthetic mid-price trace; it is not the older historical dataset under `data/`.

## Architecture and persistence

```text
Synthetic features → numeric regime detector → market advisory
Synthetic telemetry → independent service monitor → service incident
                                      ↓
                     SQLite incident + frozen evidence job
                                      ↓
                    separate classifier/explanation worker
                                      ↓
                   incident result → SSE dashboard / handover
```

The worker has an eight-second provider deadline, deterministic timeout fallback and at most two attempts for unexpected errors. Sampling continues independently. Duplicate/out-of-order observation seconds are rejected; gaps reset confirmation windows. Incident/job state persists by default in `.runtime/incidents.sqlite3` (ignored by Git). Set `INCIDENT_STORE_PATH=:memory:` for disposable runs. Use one server process with a given store; this is not multi-worker/HA coordination. Retain the SQLite file and its WAL safely for recovery; records are not automatically pruned.

UI latency is **worker time**, excluding detector confirmation and queue waiting. A ten-second end-to-end objective is unvalidated. The agent summarizes supplied evidence; no independent log or telemetry tools are connected.

## Solace / Agent Mesh boundary

With `SOLACE_HOST` empty, everything runs locally. Configured transport optionally mirrors these events using best-effort Direct delivery:

- `fx/market/EURUSD/stats`
- `fx/regime/EURUSD/change` for market advisories
- `fx/operations/incident` for service incidents
- `agent/fx-regime/result`

The current engine does not consume real price/telemetry feeds or dispatch requests through SAM. The local durable journal owns explanation work. The raw tick `FeatureEngine`, `sam-config/`, `infra/` and `deploy/` remain integration scaffolding. Do not describe the demo as an end-to-end production Agent Mesh deployment.

## Verify

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
node --check web/app.js
```

Tests cover the original regime logic, market/service separation, silent feeds, missing telemetry, distinct-second confirmation, recovery lifecycle, worker independence, deadline fallback, bounded failures, restart/deduplication and grounded explanations.

## Deployment

The Pages site runs the self-contained replay described above. The server-backed version still needs Python and a persistent writable journal. Existing AWS manifests and scripts are retained for review, not certified here. Their defaults create chargeable AWS resources; do not run them as part of local setup.

Before any production exposure, add authentication/authorization to state-changing endpoints, real telemetry adapters, approved investigation tools, durable SAM handoff and incident replay qualification. See the [pilot checklist](docs/citi-operations-design.md#production-pilot-before-claiming-robustness).

### Update the existing AWS dashboard only

Build and push a tested `linux/amd64` image to the existing ECR repository, then run:

```bash
FX_IMAGE='ECR_REPOSITORY@sha256:TESTED_DIGEST' deploy/scripts/update-dashboard.sh
```

This updates the existing `sam-fx/fx-regime` deployment without running Terraform,
reinstalling Agent Mesh or changing network access rules. It preserves existing broker
settings and secret references, disables external model calls, and mounts a 1 GiB gp3
volume for the incident journal. One replica with a Recreate rollout avoids concurrent
SQLite writers; a short interruption is expected during rollout. The previous deployment
specification is saved under ignored `.generated/` for rollback. Cluster API access and a
valid AWS SSO session are prerequisites.
