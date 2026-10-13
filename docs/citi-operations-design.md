# FX operations adaptation — public research and design

Research reviewed 13 October 2026. This is an independent design inference from public material, not an account of Citi's private architecture, incidents, SLAs or requirements. The dashboard intentionally retains neutral branding and synthetic service names.

## What seems most useful

**Help a support engineer establish whether prices are reaching the right consumers, identify the affected path, and hand off a defensible incident record.** Market conditions provide context. Service health needs its own detector: an inactive feed can be the most important failure precisely when market statistics look quiet.

Citi's public FX derivatives/risk production-support role lists continuous monitoring, service-level stability, regional handovers, impact assessment, escalation, release analysis and incident records. This is relevant adjacent evidence; it does not establish the exact responsibilities or topology of the eFX infrastructure team. [Citi job description, posted 23 September 2026](https://jobs.citi.com/job/pune/foreign-exchange-fx-derivatives-and-risk-production-support-senior-analyst/287/100296005808).

Citi's FX vendor review emphasizes connectivity, operational improvements, integration and governance. That supports a focused operational workflow with explicit evidence, rather than adding a general-purpose market chatbot. [Citi FX vendor review, 25 June 2025](https://www.citigroup.com/global/news/press-release/2025/citifx-review-market-impact-considerations-fx-vendors-innovate-competitive).

Citi describes global FX services and multiple connectivity interfaces. Regional comparisons are therefore a plausible design direction, but the two paths in this demo are invented fixtures, not discovered Citi systems. [Citi FX business overview](https://www.citigroup.com/global/businesses/markets/fx).

## Priorities implemented

| Operational need | Change in this version | Useful outcome |
| --- | --- | --- |
| Separate a busy market from a service problem | Independent market and service-health summaries; pure market stress creates an advisory | Avoid treating every price move as an infrastructure incident |
| Notice silence and lost visibility | Quote age, disconnected sessions, zero ingress, telemetry freshness and UNKNOWN state | Detect failures the upward-only anomaly score misses |
| Identify the affected path | Regional consumer IDs, ingress/egress, p99 latency, Direct discards and sequence gaps | Compare a failing path with its peer before choosing an owner |
| Give actionable evidence | Frozen statistics, observed path health, synthetic recent-change context, owner and runbook | A bounded starting point for an operator investigation |
| Support follow-the-sun operations | Persistent incident journal, acknowledgement, sustained recovery, resolution and JSON handover | Retain the operational story across a process restart |
| Keep monitoring independent of models | Separate worker, durable local work queue, provider deadline, deterministic fallback | Slow explanation calls do not stop one-second sampling |
| Avoid alert storms | Three distinct abnormal seconds, one incident per active path episode, five healthy seconds for recovery | Avoid one agent call per quote or transient observation |

Runbooks distinguish Direct slow-subscriber/discard behavior from Guaranteed spool, unacknowledged-message and oldest-message metrics. Those are different delivery mechanisms; an abstract `consumer_lag` cannot establish both. The visible demo paths use Direct delivery. [Solace performance monitoring](https://docs.solace.com/Monitoring/Perf-Mon.htm), [Solace delivery resources](https://docs.solace.com/Messaging/Managing-Event-Delivery-Resources.htm).

## Demonstration sequence

1. **Market move:** volatility, spread and activity rise; both services stay healthy. The result is an advisory with no service incident.
2. **Slow consumer:** London consumer egress falls, latency and Direct discard/sequence-gap counts rise. New York remains within the supplied demo limits. One path incident includes recent-change context without asserting causality.
3. **Silent feed:** London disconnects and quote age increases while aggregate market conditions remain normal. Service detection opens an incident without a STRESSED regime prerequisite.
4. **Missing telemetry:** London observations become stale. Visibility is UNKNOWN; the record requests an independent health check rather than claiming an outage.
5. **Market + delivery stress:** market evidence and delivery impairment coexist; classification is BOTH.

Each scenario supplies twelve one-second observations and then returns to a normal stream. Restore normal can end it early. Thresholds, P2/P3 labels, owners and durations are demonstration policy only. Evidence stays frozen at confirmation while the service table continues to update. An incident must recover for five consecutive fresh observations before it can be resolved.

## What the agent actually does

The local worker classifies and summarizes the supplied evidence, then suggests read-only checks. It does **not** query logs, query SEMP, investigate independently, place trades, alter subscriptions, restart consumers or fail over feeds. Three desk buttons produce prepared answers from the selected evidence. External classification/explanation is opt-in; default operation makes no model calls.

Optional model output remains untrusted operational prose, even when it passes JSON validation. Typed classification is bounded to MARKET/INFRASTRUCTURE/BOTH/UNCLEAR. Deterministic decisions have `source=rules` and confidence zero because no calibrated probability is available. A nearby macro headline is only context.

The current runtime is a local FastAPI service. SQLite provides single-process incident/job persistence and local correlation-ID deduplication. It is not an HA incident platform or broker exactly-once guarantee. An interrupted running job is retried on process startup; a provider may be invoked again after a crash. Unexpected worker failures have a two-attempt budget and remain visible in handover. Backlog is queued on disk, with one worker; there is no fleet-wide rate control or capacity qualification.

Configured Solace transport is an optional best-effort **Direct mirror** of statistics, signals and results. It does not currently implement a Guaranteed agent-request/result path through Agent Mesh. The existing `sam-config/` and infrastructure manifests are scaffolding and have not been validated for this adaptation. They must not be presented as a demonstrated SAM integration.

## Production pilot before claiming robustness

1. Agree a narrow scope with the actual team: one source, a pair of regional delivery paths, an inventory of consumers, owners and approved runbooks. Validate that availability, freshness and loss are the operational concerns; do not substitute this public research for discovery.
2. Ingest timestamped market updates, receipt timestamps, broker endpoint/client counters and consumer heartbeats. Define counter-reset handling, clock-skew bounds, disconnect semantics and per-instrument trading-session expectations. Five-return volatility requires contiguous one-second observations. The existing `FeatureEngine` is not wired to the demo and is not a production-certified tick adapter.
3. Configure baselines by session, instrument and feed, with scale floors, warm-up, missing-data behavior and maintenance windows. The demo uses a seeded 300-sample baseline and fixed thresholds. A robust z-score alone does not validate the detector; correlated features and serial samples invalidate naive Gaussian false-alarm claims.
4. Add read-only investigation tools for approved SEMP queries, source/consumer logs and deployment records. Record source, observation time, query bounds and result IDs. Require abstention when evidence is absent or contradictory. Evaluate explanations for unsupported claims, not just valid JSON.
5. Use durable broker queues, bounded redelivery, poison-message handling and an outbox/result deduplication design for the real event handoff. Retain correlation IDs across detector, classifier, SAM and dashboard. Verify restart/reconnect under duplicate, delayed and lost messages.
6. Add SSO/RBAC, authenticated audit identities, tenant/topic permissions, retention, secret handling and provider/data approvals before connecting non-public data. This local demo's incident endpoints have no authentication and must not be exposed as a production incident console.
7. Replay labeled incidents and ordinary sessions: quiet markets, opens/fixes, scheduled announcements, source outages, single-region delivery failures, downstream pauses, telemetry loss and recoveries. Measure incident-level recall, false alerts per service-day, detection delay p50/p95/p99, duplicate rate, unknown coverage and operator correction rate. Compare against existing monitoring and a deterministic runbook baseline.
8. Measure whether it shortens time to identify the affected path and produces a useful handover. Claim reduced diagnosis time only after a controlled operator evaluation. Financial impact, execution quality and cost savings are not measured here.

## Speed target

Separate onset → confirmation, confirmation → queue claim, worker time, and result → visible dashboard. The UI's worker latency is a measured local duration; it explicitly excludes detection and queue waiting. Service confirmation needs three distinct one-second observations. Recovery needs five fresh healthy observations. The default provider deadline is eight seconds **after the worker starts**, so this configuration is not an end-to-end ten-second guarantee. For a ten-second pilot target, allocate the budget across those stages and validate p95/p99 under bursts, retries, reconnects and cold starts. Deterministic mode can be fast without proving remote production latency.
