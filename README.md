# sam-fx · off-market investigator

## Off-market detection and investigation

The primary demo asks **“Are we off-market, and why?”** Compare the **NYC delivered quote**,
**Tokyo source quote** and **independent-path reference consensus**. All prices, reference
contributors, Corvil metrics and Solace SEMP v1 observations remain simulated. AWS can use
its configured server-side LLM; Pages runs prepared explanations with no provider requests.

Five controls tell the story:

- **Simulate stale delivery:** the reference and Tokyo source reprice by 18 pips while NYC
  retains its old quote. Corvil RTT and retransmissions increase, the SEMP transmit window
  closes, and Guaranteed queue depth rises. The investigation may localize delivery pressure
  to `FX-PRICE-NYC-01`, consumer `10.30.1.20:43172`, and `NYC-FX-PRICE-Q`.
- **Source divergence:** the fresh Tokyo quote is 6 pips from the reference; NYC follows it.
  Infrastructure is healthy. Investigate the source/pricing configuration, not TCP.
- **Real market move:** all price views follow the move. No off-market incident or LLM call.
- **One bad reference:** two contributors agree and a third is excluded. No incident or LLM call.
- **Reference lost:** quorum is unavailable. Withhold the price verdict and investigate
  reference quality; never infer that the price is wrong or a connection has failed.

The deterministic comparator requires at least two distinct, agreeing reference contributors
on the same EUR/USD spot indicative basis. Source age must be ≤500 ms, timestamp separation
≤100 ms, clock uncertainty ≤20 ms and contributor mid dispersion ≤0.5 pips. It compares
**quote bands**, not just mids: the gap is `max(0, our_bid - ref_ask, ref_bid - our_ask) × 10,000`.
Three consecutive gaps ≥1.0 pip confirm OFF_MARKET. Gaps in observation time reset votes;
duplicate/out-of-order comparisons are rejected. Five aligned observations confirm recovery.
These are illustrative policies, not calibrated bank thresholds. A wide overlapping spread
alone is not classified off-market. UNKNOWN is distinct from a price discrepancy.

The live mini-curve compares delivered and reference mids. The three stacked feed boxes show
price observations, Corvil packet-derived metrics and SEMP v1 TCP/Guaranteed queue metrics.
The main chart, detailed TCP fields, reference checks and incident journal remain expandable.
The numeric verdict and frozen comparison are visible independently of the model explanation.

A confirmed event wakes the bounded two-request LLM/tool investigation. `inspect_fx_path`
reads an immutable package containing reference contributors, price comparison, source and
consumer evidence, Corvil/SEMP metrics and an unaffected peer. The model briefs Greg,
identifies a supported suspect and suggests a read-only next check. Suspect categories and
graph links are validated against the supplied comparison. The model cannot change the
numeric verdict, invent graph nodes or perform trading/remediation actions. Grey graph links
are measured comparisons; amber links are hypotheses, not proof of causation. A prepared
fallback is clearly labelled if the provider fails.

See [comparison policy and production boundaries](docs/off-market-design.md). Legacy AIOps
and service-health API scenarios remain for regression testing. SEMP v1 fields still include
SRTT/variation, retransmit deltas, windows, blocking, buffers, queue depth/oldest age,
unacknowledged messages and ingress/egress. Queue messages are distinct from TCP send bytes.

AWS uses `FX_ENABLE_LLM=true deploy/scripts/update-dashboard.sh` with existing secret references.
Jev is disabled. The local durable worker owns investigation delivery; the optional Solace
Direct event mirror and SAM scaffolding remain unchanged. This is not a validated end-to-end
SAM orchestration integration or a real market-data collector deployment.


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

Open <http://localhost:8080>. Default explanations and the three desk answers are deterministic; no LLM is required. `ENABLE_EXTERNAL_PROVIDERS=true` enables the configured Groq LLM; Jev additionally requires `ENABLE_JEV_PROVIDER=true`. Do not send private data without the appropriate approval.

## Try it

- **Market move:** a market advisory while delivery remains healthy.
- **Slow consumer:** one regional path degrades; peer evidence helps localize it.
- **Silent feed:** an incident despite normal market statistics.
- **Missing telemetry:** visibility becomes UNKNOWN, not healthy or a proven outage.
- **Market + delivery stress:** abnormal market activity and delivery impairment together.

The off-market scenarios last 24 observations; legacy scenarios last twelve. **Restore normal** ends one early. A service incident requires three consecutive abnormal observations, recovery requires five healthy observations, and **Resolve incident** becomes available after recovery. **Acknowledge** records the demo operator action. Select an incident to see its frozen evidence and runbook. **Export handover** downloads the journal.

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

### Updating price curve

The expandable EUR/USD chart displays the simulated delivered mid-price and current bid/ask and spread.
Choose a 1-, 3- or 5-minute window and 5-, 15- or 30-second candles. Hollow blue candles rise;
filled blue candles fall. Hover or use arrow keys to inspect observed OHLC values. The last bar
is forming. SMA 10 toggles a ten-candle simple moving average; the overview highlights the selected
trailing window. Candles use only collected prices; missing buckets are left empty.
The server keeps the latest 301 source observations in memory for reconnects; history starts anew
on a process restart. Pages accumulates replay prices while the tab is open. Missing observations
leave gaps in the candles, and a stalled stream holds its last price with a paused indicator. No real market
data provider is connected.
