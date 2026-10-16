"""Deterministic service-health policy, independent of market volatility.

Thresholds are demo defaults, not a bank SLA. Missing or stale observations never
count as a healthy sample. Confirmation uses distinct consecutive seconds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .models import ServiceHealth, ServiceObservation

RUNBOOKS = {
    "aiops": {
        "title": "Off-market price investigation",
        "owner": "FX platform support (demo)",
        "checks": [
            "Validate independent reference quorum, freshness, clocks and indicative spot basis.",
            "Compare reference bid/ask, Tokyo source and NYC delivered prices and timestamps.",
            "A market move or a single reference outlier does not prove an off-market quote.",
            "Match Corvil flow to broker CLI client ID, VPN, both TCP endpoints and session epoch.",
            "Compare source freshness and NYC peer delivery before assigning a suspect component.",
            "Compare Corvil loss and windows with CLI blocking before blaming the network.",
            "Compare flow 42 unacked count with its limit; TCP ACK is not app settlement.",
            "Read blocked percentage as a recent-window value, not an instantaneous sample.",
            "Distinguish TCP send-buffer bytes from Guaranteed queue messages and oldest age.",
            "Review the suspected propagation chain with Greg; causal arrows remain hypotheses.",
        ],
    },
    "feed": {
        "title": "Missing or stale prices",
        "owner": "Market data support (demo)",
        "checks": [
            "Compare publisher heartbeat and ingress with the peer path.",
            "Check session state, last sequence and source timestamps.",
            "Identify affected instruments and downstream price freshness.",
            "Escalate to the configured feed owner; do not switch feeds automatically.",
        ],
    },
    "consumer": {
        "title": "Consumer delivery degradation",
        "owner": "Pricing application support (demo)",
        "checks": [
            "Compare ingress and egress on this consumer and its peer.",
            (
                "For Direct delivery inspect slow-subscriber/discard counters; for "
                "Guaranteed inspect spool, unacked messages and oldest age."
            ),
            "Check application processing, runtime pauses and recent deployments.",
            "Confirm impact before proposing any restart or failover.",
        ],
    },
    "telemetry": {
        "title": "Monitoring visibility lost",
        "owner": "Observability support (demo)",
        "checks": [
            "Check collector heartbeat, timestamp and clock synchronization.",
            "Cross-check service health through an independent monitoring path.",
            "Treat missing metrics as unknown; do not infer a service outage or recovery.",
        ],
    },
}


class ServiceMonitor:
    def __init__(self, confirmation: int = 3, recovery: int = 5) -> None:
        self.confirmation = confirmation
        self.recovery = recovery
        self._last: datetime | None = None
        self._votes: dict[str, tuple[str, int]] = {}
        self._known: dict[str, ServiceObservation] = {}

    def update(self, now: datetime, observations: list[ServiceObservation]) -> list[ServiceHealth]:
        second = now.replace(microsecond=0)
        if self._last is not None:
            if second <= self._last:
                raise ValueError("duplicate or out-of-order service observation second")
            if (second - self._last).total_seconds() != 1:
                self._votes.clear()
        self._last = second
        present = {item.service_id: item for item in observations}
        self._known.update(present)
        health = []
        for service_id, item in self._known.items():
            age = (now - item.timestamp).total_seconds()
            findings = []
            status: Literal["HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"] = "HEALTHY"
            book = "consumer"
            if service_id not in present or age > 3 or age < -1:
                status, book = "UNKNOWN", "telemetry"
                findings = ["Telemetry missing or stale; service health cannot be established."]
            elif not item.connected or item.quote_age_ms >= 3000 or item.ingress_rate == 0:
                status, book = "UNAVAILABLE", "feed"
                findings = [
                    (
                        f"Quote age {item.quote_age_ms:.0f} ms; ingress "
                        f"{item.ingress_rate:.0f}/s; "
                        f"session {'connected' if item.connected else 'disconnected'}."
                    )
                ]
            else:
                if item.p99_latency_ms > 50:
                    findings.append(
                        f"Delivery p99 {item.p99_latency_ms:.0f} ms exceeds the 50 ms demo limit."
                    )
                if item.oldest_message_ms > 1000 or item.backlog >= 100:
                    findings.append(
                        f"Backlog {item.backlog}; oldest waiting message "
                        f"{item.oldest_message_ms:.0f} ms."
                    )
                if item.ingress_rate > 0 and item.egress_rate < item.ingress_rate * 0.8:
                    findings.append(
                        f"Egress {item.egress_rate:.0f}/s is below ingress "
                        f"{item.ingress_rate:.0f}/s."
                    )
                if item.discard_delta or item.sequence_gap_delta:
                    findings.append(
                        f"This interval: {item.discard_delta} discards; "
                        f"{item.sequence_gap_delta} sequence gaps."
                    )
                if findings:
                    status = "DEGRADED"
            previous, count = self._votes.get(service_id, ("", 0))
            count = count + 1 if previous == status else 1
            self._votes[service_id] = (status, count)
            health.append(
                ServiceHealth(
                    observation=item,
                    status=status,
                    findings=findings,
                    runbook=book,
                    confirmed=count
                    >= (self.recovery if status == "HEALTHY" else self.confirmation),
                    observed_at=now,
                )
            )
        return health
