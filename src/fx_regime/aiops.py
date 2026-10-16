"""Simulated source adapters and a deterministic, workload-aware confidence detector.

Each source is explicitly synthetic. IDs join the same demo path and TCP session.
Scores are robust baseline deviations, never calibrated probabilities of correctness.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import Literal

from .broker_cli import diagnose
from .broker_cli import snapshot as cli_snapshot
from .models import (
    ConfidenceState,
    ExplanationEdge,
    ExplanationGraph,
    ExplanationNode,
    FeatureValues,
    InvestigationCheck,
    SourceEvidence,
)
from .offmarket import OFFMARKET_SCENARIOS, QuoteSimulation

AIOPS_SCENARIOS = {
    "tokyo_burst",
    "tcp_pressure",
    "queue_pressure",
    "market_only",
    "aiops_unknown",
} | OFFMARKET_SCENARIOS
CONNECTION = {
    "client_id": "FX-PRICE-NYC-01",
    "vpn": "fx-demo",
    "broker": "nyc-broker-01",
    "local": "10.30.0.5:55555",
    "remote": "10.30.1.20:43172",
    "queue": "NYC-FX-PRICE-Q",
    "session_epoch": "demo-session-01",
    "broker_epoch": "demo-boot-01",
    "delivery": "GUARANTEED",
}
# Floors prevent zeros/near-constant baseline metrics from creating infinite scores.
FLOORS = {
    "rtt_ms": 0.4,
    "retransmit_pct": 0.2,
    "blocked_pct": 2.0,
    "queue_depth": 25.0,
    "quote_age_ms": 100.0,
}
NORMAL = {
    "rtt_ms": 1.2,
    "retransmit_pct": 0.02,
    "blocked_pct": 0.0,
    "queue_depth": 3.0,
    "quote_age_ms": 80.0,
}


class ConfidenceMonitor:
    def __init__(self) -> None:
        self.offmarket_mode = True
        self.quotes = QuoteSimulation()
        self.baseline = {
            key: deque([value * (1 + (i % 7 - 3) * 0.01) for i in range(300)], maxlen=300)
            for key, value in NORMAL.items()
        }
        self.votes = 0
        self.healthy_votes = 0
        self.onset: datetime | None = None
        self.last: datetime | None = None

    def observe(
        self, scenario: str, offset: int, now: datetime, market: FeatureValues, mid: float = 1.11882
    ) -> ConfidenceState:
        if self.last and (now - self.last).total_seconds() != 1:
            self.votes = self.healthy_votes = 0
        self.last = now
        burst = scenario in {
            "tokyo_burst",
            "market_only",
            "offmarket_stale",
            "offmarket_network",
            "offmarket_ack",
            "offmarket_blind",
            "market_reprice",
        }
        tcp = scenario == "tcp_pressure" or (
            scenario in {"tokyo_burst", "offmarket_stale", "offmarket_network"} and offset >= 2
        )
        queue = scenario == "queue_pressure" or (
            scenario
            in {
                "tokyo_burst",
                "offmarket_stale",
                "offmarket_network",
                "offmarket_ack",
                "offmarket_blind",
            }
            and offset >= 3
        )
        missing = scenario == "aiops_unknown"
        values = dict(NORMAL)
        if tcp:
            values.update(rtt_ms=42.0, retransmit_pct=3.8, blocked_pct=68.0)
        if scenario == "offmarket_stale" and offset >= 2:
            values.update(
                rtt_ms=1.4, retransmit_pct=0.02, blocked_pct=min(100.0, (offset - 1) / 60 * 100)
            )
        if scenario == "offmarket_network" and offset >= 2:
            values["blocked_pct"] = 0.0
        if queue:
            values["queue_depth"] = 850.0 + offset * 70
        if (tcp or queue) and (scenario != "tokyo_burst" or offset >= 4):
            values["quote_age_ms"] = 380.0 + offset * 100
        comparison = self.quotes.observe(scenario, offset, now, mid)
        if scenario in OFFMARKET_SCENARIOS:
            self.offmarket_mode = True
        elif scenario != "baseline":
            self.offmarket_mode = False
        offmarket_mode = self.offmarket_mode
        if offmarket_mode:
            values["quote_age_ms"] = comparison.delivered_age_ms
        scores = {}
        for key, value in values.items():
            center = median(self.baseline[key])
            scale = max(FLOORS[key], 1.4826 * median(abs(x - center) for x in self.baseline[key]))
            scores[key] = min(6.0, max(0.0, (value - center) / scale))
        score = (
            0.25 * scores["rtt_ms"]
            + 0.15 * scores["retransmit_pct"]
            + 0.15 * scores["blocked_pct"]
            + 0.25 * scores["queue_depth"]
            + 0.2 * scores["quote_age_ms"]
        )
        abnormal = (
            comparison.status != "WITHIN_BAND"
            if offmarket_mode
            else missing or score >= 2.0 or values["quote_age_ms"] >= 1000
        )
        self.votes = self.votes + 1 if abnormal else 0
        self.healthy_votes = 0 if abnormal else self.healthy_votes + 1
        if abnormal and not self.onset:
            self.onset = now
        if self.healthy_votes >= 5:
            self.onset = None
        confirmed = self.votes >= 3 if abnormal else self.healthy_votes >= 5
        status: Literal["WITHIN_LIMITS", "WATCH", "AT_RISK", "IMPAIRED", "UNKNOWN"] = (
            "UNKNOWN"
            if missing
            else "IMPAIRED"
            if self.votes >= 3 and values["quote_age_ms"] >= 1000
            else "AT_RISK"
            if self.votes >= 3
            else "WATCH"
            if abnormal
            else "WITHIN_LIMITS"
        )
        if offmarket_mode:
            confirmed = comparison.confirmed
            status = (
                "UNKNOWN"
                if comparison.status == "UNKNOWN"
                else "IMPAIRED"
                if comparison.status == "OFF_MARKET"
                else "WATCH"
                if comparison.status == "SUSPECTED"
                else "WITHIN_LIMITS"
            )
            self.votes = comparison.consecutive
        reasons = []
        if burst:
            reasons.append(
                "Tokyo quote activity increased; market activity alone does not "
                "reduce data confidence."
            )
        if tcp:
            reasons.append(
                "Corvil path evidence and broker CLI session/flow statistics are compared for NYC."
            )
        if queue:
            reasons.append(
                "Guaranteed queue depth increased; source freshness and peer "
                "delivery are compared separately."
            )
        if missing:
            reasons.append(
                "Corvil and broker CLI observations are stale; data quality cannot be established."
            )
        if values["quote_age_ms"] >= 1000:
            reasons.append("Consumer quote age exceeds the illustrative 1,000 ms freshness budget.")
        if offmarket_mode:
            reasons.extend(comparison.reasons)
        if not abnormal and comparison.status == "WITHIN_BAND":
            for key, value in values.items():
                self.baseline[key].append(value)
        measured = now - timedelta(seconds=10) if missing else now
        network = scenario == "offmarket_network" and offset >= 2
        consumer = scenario == "offmarket_stale" and offset >= 2
        ack_stall = scenario == "offmarket_ack" and offset >= 3
        sources = [
            SourceEvidence(
                change_offset_s=0 if burst else None,
                evidence_id="market",
                source="MARKET",
                timestamp=now,
                region="TOKYO",
                summary="Tokyo EUR/USD source activity; prices remain internally consistent.",
                metrics={
                    "quote_rate": 180.0 if burst else market.quote_rate,
                    "spread_pips": market.spread_pips,
                    "volatility": market.realized_volatility,
                    "source_quote_age_ms": 45.0,
                    "source_sequence_gaps": 0.0,
                },
            ),
            SourceEvidence(
                change_offset_s=(2 if scenario in {"tokyo_burst", "offmarket_stale"} else 0)
                if tcp
                else None,
                evidence_id="corvil_tcp",
                source="CORVIL",
                timestamp=measured,
                region="NEW_YORK",
                summary=(
                    "Simulated packet-derived analytics for TYO-NYC-FX-01 and its NYC "
                    "consumer session."
                ),
                metrics={
                    "rtt_ms": values["rtt_ms"],
                    "retransmit_pct": values["retransmit_pct"],
                    "path_p99_ms": 480.0
                    if network
                    else 1.8
                    if offmarket_mode
                    else 160.0 + (320.0 if tcp or queue else 0.0),
                    "source_to_broker_p99_ms": 1.1,
                    "broker_to_consumer_p99_ms": 480.0 if network else 1.8,
                    "peer_receive_window_bytes": 0.0 if consumer else 65536.0,
                    "zero_window_probes_delta": 2.0 if consumer else 0.0,
                    "peer_rtt_ms": 1.3,
                    "capture_drops": 0.0,
                    "capture_clock_uncertainty_us": 10.0,
                    "client_id": CONNECTION["client_id"],
                    "local_endpoint": CONNECTION["local"],
                    "remote_endpoint": CONNECTION["remote"],
                    "session_epoch": CONNECTION["session_epoch"],
                    "peer_quote_age_ms": 85.0,
                },
            ),
            SourceEvidence(
                change_offset_s=(2 if scenario in {"tokyo_burst", "offmarket_stale"} else 0)
                if tcp
                else None,
                evidence_id="broker_tcp",
                source="BROKER_CLI",
                timestamp=now - timedelta(seconds=30)
                if scenario == "offmarket_blind"
                else measured,
                region="NEW_YORK",
                summary="Normalized simulated broker CLI TCP connection statistics.",
                metrics={
                    "srtt_us": values["rtt_ms"] * 1000,
                    "rttvar_us": 120.0 if consumer else 9600.0 if tcp else 120.0,
                    "fast_retransmit_delta": 0.0 if consumer else 38.0 if tcp else 0.0,
                    "timed_retransmit_delta": 0.0 if consumer else 6.0 if tcp else 0.0,
                    "blocked_pct": values["blocked_pct"],
                    "send_queue_bytes": 524288.0 if tcp else 1024.0,
                    "receive_queue_bytes": 4096.0 if tcp else 0.0,
                    "advertised_window_bytes": 65536.0,
                    "transmit_window_bytes": 65536.0 if network else 0.0 if tcp else 65536.0,
                    "congestion_window_bytes": 131072.0
                    if consumer
                    else 5840.0
                    if tcp
                    else 131072.0,
                    "slow_start_threshold_bytes": 5840.0 if network else 65536.0,
                    "received_out_of_order_delta": 6.0 if network else 0.0,
                    "blocked_window_seconds": 60.0,
                    "counter_interval_seconds": 1.0,
                    "client_egress_queue_bytes": 65536.0 if consumer else 2048.0,
                    "tcp_state": "ESTABLISHED",
                },
            ),
            SourceEvidence(
                change_offset_s=(3 if scenario in {"tokyo_burst", "offmarket_stale"} else 0)
                if queue
                else None,
                evidence_id="broker_queue",
                source="BROKER_CLI",
                timestamp=now - timedelta(seconds=30)
                if scenario == "offmarket_blind"
                else measured,
                region="NEW_YORK",
                summary=(
                    "Simulated Guaranteed queue statistics; queue backlog is distinct "
                    "from TCP send bytes."
                ),
                metrics={
                    "queue_depth": values["queue_depth"],
                    "oldest_message_ms": values["quote_age_ms"] if queue else 20.0,
                    "ingress_rate": 180.0 if burst else market.quote_rate,
                    "egress_rate": 0.0
                    if ack_stall or consumer
                    else 24.0
                    if queue
                    else 180.0
                    if burst
                    else market.quote_rate,
                    "unacked_messages": 128.0
                    if ack_stall
                    else 32.0
                    if consumer
                    else 64.0
                    if network
                    else 120.0
                    if queue
                    else 1.0,
                    "max_delivered_unacked_per_flow": 128.0,
                    "unacked_limit_headroom": 0.0
                    if ack_stall
                    else 96.0
                    if consumer
                    else 64.0
                    if network
                    else 8.0
                    if queue
                    else 127.0,
                    "flow_id": 42.0,
                    "flow_state": "ACTIVE",
                    "redelivered_delta": 0.0,
                    "expired_delta": 0.0,
                },
            ),
            SourceEvidence(
                change_offset_s=(
                    2 if scenario == "offmarket_stale" else 4 if scenario == "tokyo_burst" else 0
                )
                if (tcp or queue) and values["quote_age_ms"] > 80
                else None,
                evidence_id="data_quality",
                source="CONSUMER",
                timestamp=now,
                region="NEW_YORK",
                summary=(
                    "Simulated consumer freshness measurement; no payload corruption is asserted."
                ),
                metrics={
                    "quote_age_ms": values["quote_age_ms"],
                    "freshness_budget_ms": 1000.0,
                    "sequence_gaps": 0.0,
                },
            ),
        ]
        if offmarket_mode:
            sources[0].metrics.update(source_mid=comparison.source_mid)
            sources[-1].metrics.update(delivered_mid=comparison.delivered_mid)
            sources.append(
                SourceEvidence(
                    evidence_id="reference",
                    source="MARKET",
                    timestamp=now,
                    region="REFERENCE",
                    summary="Synthetic independent-path indicative quote consensus; not "
                    "executable fair value.",
                    metrics={
                        "contributors_used": float(len(comparison.contributors_used)),
                        "reference_mid": comparison.reference_mid or 0.0,
                        "band_gap_pips": comparison.outside_band_pips or 0.0,
                    },
                )
            )
        result = ConfidenceState(
            status=status,
            confirmed=confirmed,
            scenario=scenario,
            timestamp=now,
            market_regime="STRESSED" if burst else "NORMAL",
            technical_score=round(score, 2),
            confirmation_count=self.votes,
            reasons=reasons,
            zscores=scores,
            sources=sources,
            offmarket=comparison if offmarket_mode else None,
            connection=CONNECTION,
            onset=self.onset,
        )
        result.broker_cli = cli_snapshot(result)
        if result.offmarket:
            result.diagnosis = diagnose(result)
        return result


def source_checks(state: ConfidenceState) -> list[InvestigationCheck]:
    return [
        InvestigationCheck(
            name="Compare independent reference, Tokyo source and NYC delivered quotes"
            if state.offmarket
            else "Compare Tokyo activity and source freshness",
            source="MARKET",
            evidence_ids=["market", "reference", "data_quality"] if state.offmarket else ["market"],
        ),
        InvestigationCheck(
            name="Compare NYC socket with an unaffected peer",
            source="CORVIL",
            evidence_ids=["corvil_tcp"],
        ),
        InvestigationCheck(
            name="Inspect TCP windows, retransmits and Guaranteed queue",
            source="BROKER_CLI",
            evidence_ids=["broker_tcp", "broker_queue", "data_quality"],
        ),
    ]


def explanation_graph(state: ConfidenceState, requested: Sequence[str]) -> ExplanationGraph:
    if state.offmarket:
        return offmarket_graph(state, requested)
    sources = {s.evidence_id: s for s in state.sources}
    market, tcp, queue, quality = [
        sources[k].metrics for k in ("market", "broker_tcp", "broker_queue", "data_quality")
    ]
    nodes = [
        ExplanationNode(
            change_offset_s=sources["market"].change_offset_s,
            node_id="tokyo_source",
            label="Tokyo market activity",
            region="TOKYO",
            detail=f"{market['quote_rate']:.0f} quotes/s · source fresh",
            evidence_ids=["market"],
        ),
        ExplanationNode(
            change_offset_s=sources["broker_tcp"].change_offset_s,
            node_id="nyc_tcp",
            label="NYC consumer port 43172",
            region="NEW YORK",
            detail=f"RTT {float(tcp['srtt_us']) / 1000:.1f} ms · blocked {tcp['blocked_pct']:.0f}%",
            evidence_ids=["corvil_tcp", "broker_tcp"],
        ),
        ExplanationNode(
            change_offset_s=sources["broker_queue"].change_offset_s,
            node_id="nyc_queue",
            label="NYC-FX-PRICE-Q",
            region="NEW YORK",
            detail=(
                f"Flow 42 unacked {queue['unacked_messages']:.0f}/128"
                if state.diagnosis and state.diagnosis.hypothesis == "ACK_STALL"
                else "CLI unavailable"
                if state.diagnosis and state.diagnosis.hypothesis == "UNDETERMINED"
                else f"{queue['queue_depth']:.0f} queued · Guaranteed"
            ),
            evidence_ids=["broker_queue"],
        ),
        ExplanationNode(
            change_offset_s=sources["data_quality"].change_offset_s,
            node_id="data_quality",
            label="EUR/USD freshness",
            region="NYC CONSUMER",
            detail=f"Quote age {quality['quote_age_ms']:.0f} ms",
            evidence_ids=["data_quality"],
        ),
    ]
    candidates = {
        "market_tcp": (
            "tokyo_source",
            "nyc_tcp",
            "Load may amplify pressure",
            ["market", "broker_tcp"],
        ),
        "tcp_queue": (
            "nyc_tcp",
            "nyc_queue",
            "Possible backpressure",
            ["broker_tcp", "broker_queue"],
        ),
        "tcp_data": (
            "nyc_tcp",
            "data_quality",
            "Possible delivery delay",
            ["broker_tcp", "data_quality"],
        ),
        "queue_data": (
            "nyc_queue",
            "data_quality",
            "Possible freshness impact",
            ["broker_queue", "data_quality"],
        ),
    }
    if float(queue["queue_depth"]) < 100:
        candidates.pop("tcp_queue")
        candidates.pop("queue_data")
    else:
        candidates.pop("tcp_data")
    if float(tcp["blocked_pct"]) < 5:
        candidates.pop("tcp_queue", None)
        candidates.pop("tcp_data", None)
    if state.scenario != "tokyo_burst":
        candidates.pop("market_tcp")
    if state.scenario in {"market_only", "aiops_unknown", "baseline"}:
        candidates.clear()
    graph = ExplanationGraph(
        nodes=nodes,
        edges=[
            ExplanationEdge(
                edge_id=k,
                source=candidates[k][0],
                target=candidates[k][1],
                label=candidates[k][2],
                evidence_ids=candidates[k][3],
            )
            for k in dict.fromkeys(requested)
            if k in candidates
        ],
    )

    if (
        state.scenario == "tokyo_burst"
        and sources["broker_tcp"].change_offset_s is not None
        and "market_tcp" not in requested
    ):
        graph.edges.insert(
            0,
            ExplanationEdge(
                edge_id="market_tcp_sequence",
                source="tokyo_source",
                target="nyc_tcp",
                label="TCP pressure observed two seconds later; causality unproven",
                kind="sequence",
                evidence_ids=["market", "broker_tcp"],
            ),
        )
    return graph


def offmarket_graph(state: ConfidenceState, requested: Sequence[str]) -> ExplanationGraph:
    comparison = state.offmarket
    assert comparison is not None
    sources = {s.evidence_id: s for s in state.sources}
    tcp, queue = sources["broker_tcp"].metrics, sources["broker_queue"].metrics
    gap = comparison.mid_delta_pips
    nodes = [
        ExplanationNode(
            node_id="reference",
            label="Independent reference",
            region="CONSENSUS",
            detail=f"{len(comparison.contributors_used)}/3 in reference quorum",
            evidence_ids=["reference"],
        ),
        ExplanationNode(
            node_id="tokyo_source",
            label="Tokyo source price",
            region="TOKYO",
            detail=f"{comparison.source_mid:.5f}",
            evidence_ids=["market"],
        ),
        ExplanationNode(
            node_id="nyc_tcp",
            label="NYC consumer port 43172",
            region="NEW YORK",
            detail=(
                "CLI unverified · cause unconfirmed"
                if state.diagnosis and state.diagnosis.hypothesis == "UNDETERMINED"
                else f"RTT {float(tcp['srtt_us']) / 1000:.1f} ms · "
                f"blocked {tcp['blocked_pct']:.0f}%"
            ),
            evidence_ids=["corvil_tcp", "broker_tcp"],
        ),
        ExplanationNode(
            node_id="nyc_queue",
            label="NYC-FX-PRICE-Q",
            region="NEW YORK",
            detail=(
                f"Flow 42 unacked {queue['unacked_messages']:.0f}/128"
                if state.diagnosis and state.diagnosis.hypothesis == "ACK_STALL"
                else "CLI unverified"
                if state.diagnosis and state.diagnosis.hypothesis == "UNDETERMINED"
                else f"{queue['queue_depth']:.0f} queued · Guaranteed"
            ),
            evidence_ids=["broker_queue"],
        ),
        ExplanationNode(
            node_id="data_quality",
            label="NYC delivered price",
            region="PRICE CHECK",
            detail=f"{comparison.delivered_mid:.5f} · "
            + (f"{gap:+.1f} pips" if gap is not None else "reference unknown"),
            evidence_ids=["data_quality", "reference"],
        ),
    ]
    edges = []
    if comparison.reference_mid is not None:
        edges.append(
            ExplanationEdge(
                edge_id="reference_data",
                source="reference",
                target="data_quality",
                label="Measured price comparison, not causality",
                kind="comparison",
                evidence_ids=["reference", "data_quality"],
            )
        )
    if comparison.reference_mid is not None:
        edges.append(
            ExplanationEdge(
                edge_id="reference_source",
                source="reference",
                target="tokyo_source",
                label=f"Source mid vs reference: {comparison.source_delta_pips:+.1f} pips",
                kind="comparison",
                evidence_ids=["reference", "market"],
            )
        )
    hypothesis = state.diagnosis.hypothesis if state.diagnosis else "UNDETERMINED"
    if hypothesis in {"CONSUMER_BACKPRESSURE", "NETWORK_DEGRADATION"}:
        allowed = {
            "tcp_queue": ("nyc_tcp", "nyc_queue", ["broker_tcp", "broker_queue"]),
            "queue_data": ("nyc_queue", "data_quality", ["broker_queue", "data_quality"]),
        }
    elif hypothesis == "ACK_STALL":
        allowed = {"queue_data": ("nyc_queue", "data_quality", ["broker_queue", "data_quality"])}
    elif hypothesis == "SOURCE_DIVERGENCE":
        allowed = {"source_data": ("tokyo_source", "data_quality", ["market", "data_quality"])}
    else:
        allowed = {}
    for key in dict.fromkeys(requested):
        if key in allowed:
            a, b, refs = allowed[key]
            edges.append(
                ExplanationEdge(
                    edge_id=key,
                    source=a,
                    target=b,
                    label="Suspected propagation",
                    evidence_ids=refs,
                )
            )
    return ExplanationGraph(nodes=nodes, edges=edges)
