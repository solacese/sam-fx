"""Scoped read-only broker CLI evidence packs and cross-source diagnostic hypotheses.

No SSH session is opened. Captures are explicitly normalized simulations. In production,
collect on the correct AD-active broker with version-aware parsing and capability checks.
"""

from __future__ import annotations

import re
from typing import Literal

from .models import (
    BrokerCliSnapshot,
    CliCapture,
    ConfidenceState,
    DiagnosticEvidence,
    PathDiagnosis,
)


def command_pack(connection: dict[str, str]) -> dict[str, str]:
    """Fixed show commands only; no wildcard expansion, clears or model-provided commands."""
    for key in ("client_id", "vpn", "queue"):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", connection[key]):
            raise ValueError("Unsupported CLI object identifier")
    client = f"show client {connection['client_id']} message-vpn {connection['vpn']}"
    queue = f"show queue {connection['queue']} message-vpn {connection['vpn']}"
    return {
        "version": "show version",
        "role": "show message-spool",
        "tcp": client + " connections wide",
        "traffic": client + " stats detail",
        "congestion": client + " stats queues",
        "client_flow": client + " message-spool-stats egress flow 42",
        "queue_config": queue + " detail",
        "queue_stats": queue + " stats",
        "queue_rates": queue + " rates",
        "queue_oldest": queue + " messages oldest count 1",
        "queue_flow": queue + " flows detail",
        "vpn": f"show message-vpn {connection['vpn']} stats detail",
    }


def snapshot(state: ConfidenceState) -> BrokerCliSnapshot:
    sources = {s.evidence_id: s for s in state.sources}
    tcp, queue = sources["broker_tcp"], sources["broker_queue"]
    commands = command_pack(state.connection)
    fields: dict[str, dict[str, float | str]] = {
        "version": {
            "target_version": "UNVERIFIED",
            "collection_mode": "SIMULATED",
            "reference_platform": "SOFTWARE",
        },
        "role": {"operational_status": "AD_ACTIVE", "spool_utilization_pct": 12.0},
        "tcp": tcp.metrics,
        "traffic": {
            "ingress_rate": queue.metrics["ingress_rate"],
            "egress_rate": queue.metrics["egress_rate"],
        },
        "congestion": {
            "client_egress_queue_bytes": tcp.metrics["client_egress_queue_bytes"],
            "congestion_discards_delta": 0.0,
        },
        "client_flow": {
            k: queue.metrics[k]
            for k in (
                "flow_id",
                "unacked_messages",
                "max_delivered_unacked_per_flow",
                "unacked_limit_headroom",
                "flow_state",
            )
        },
        "queue_config": {
            "queue": state.connection["queue"],
            "ingress": "UP",
            "egress": "UP",
            "delivery": "GUARANTEED",
            "max_delivered_unacked_per_flow": 128.0,
        },
        "queue_stats": {
            k: queue.metrics[k]
            for k in ("queue_depth", "unacked_messages", "redelivered_delta", "expired_delta")
        },
        "queue_rates": {k: queue.metrics[k] for k in ("ingress_rate", "egress_rate")},
        "queue_oldest": {
            "oldest_message_ms": queue.metrics["oldest_message_ms"],
            "age_source": "SIMULATED_ENQUEUE_METADATA",
        },
        "queue_flow": {
            "bound_client": state.connection["client_id"],
            "flow_id": 42.0,
            "flow_state": "ACTIVE",
            "unacked_messages": queue.metrics["unacked_messages"],
            "max_delivered_unacked_per_flow": 128.0,
        },
        "vpn": {
            "ingress_rate": queue.metrics["ingress_rate"],
            "unaffected_peer_egress_rate": 180.0,
            "no_subscription_match_delta": 0.0,
            "discard_delta": 0.0,
        },
    }
    return BrokerCliSnapshot(
        broker=state.connection["broker"],
        vpn=state.connection["vpn"],
        client=state.connection["client_id"],
        queue=state.connection["queue"],
        connection_epoch=state.connection["session_epoch"],
        broker_epoch=state.connection["broker_epoch"],
        local_endpoint=state.connection["local"],
        remote_endpoint=state.connection["remote"],
        sampled_at=tcp.timestamp,
        captures=[
            CliCapture(
                command_id=key,
                command=command,
                sampled_at=tcp.timestamp,
                status="UNAVAILABLE" if state.scenario == "offmarket_blind" else "SIMULATED",
                values={} if state.scenario == "offmarket_blind" else fields[key],
            )
            for key, command in commands.items()
        ],
    )


def diagnose(state: ConfidenceState) -> PathDiagnosis:
    check = state.offmarket
    assert check is not None
    sources = {s.evidence_id: s for s in state.sources}
    corvil, tcp, queue = [sources[key] for key in ("corvil_tcp", "broker_tcp", "broker_queue")]
    technical_fresh = all(
        0 <= (state.timestamp - item.timestamp).total_seconds() <= 10
        for item in (corvil, tcp, queue)
    )
    technical_fresh = (
        technical_fresh
        and float(corvil.metrics["capture_drops"]) == 0
        and float(corvil.metrics["capture_clock_uncertainty_us"]) <= 100
    )
    cli = state.broker_cli
    joined = bool(
        cli
        and cli.client == state.connection["client_id"]
        and cli.connection_epoch == state.connection["session_epoch"]
        and cli.broker == state.connection["broker"]
        and cli.vpn == state.connection["vpn"]
        and cli.ad_role == "AD_ACTIVE"
        and 0 <= (state.timestamp - cli.sampled_at).total_seconds() <= 10
        and all(
            0 <= (state.timestamp - capture.sampled_at).total_seconds() <= 10
            for capture in cli.captures
        )
        and float(tcp.metrics["counter_interval_seconds"]) > 0
        and float(tcp.metrics["fast_retransmit_delta"]) >= 0
        and float(tcp.metrics["timed_retransmit_delta"]) >= 0
        and cli.flow_id == int(queue.metrics["flow_id"])
        and cli.queue == state.connection["queue"]
        and cli.broker_epoch == state.connection["broker_epoch"]
        and cli.local_endpoint == state.connection["local"]
        and cli.remote_endpoint == state.connection["remote"]
        and corvil.metrics["local_endpoint"] == cli.local_endpoint
        and corvil.metrics["remote_endpoint"] == cli.remote_endpoint
        and corvil.metrics["session_epoch"] == cli.connection_epoch
        and corvil.metrics["client_id"] == cli.client
        and all(c.status == "SIMULATED" for c in cli.captures)
    )
    price = "The delivered quote remains within the comparable reference band."
    wire = (
        f"NYC RTT {corvil.metrics['rtt_ms']:.1f} ms; retransmits "
        f"{corvil.metrics['retransmit_pct']:.2f}%; peer RTT {corvil.metrics['peer_rtt_ms']:.1f} ms."
    )
    broker = (
        f"Transmit window {tcp.metrics['transmit_window_bytes']:.0f} B; "
        f"queue {queue.metrics['queue_depth']:.0f} msgs; "
        f"delivered-unacked {queue.metrics['unacked_messages']:.0f}/128."
    )
    hypothesis: Literal[
        "ALIGNED",
        "CONSUMER_BACKPRESSURE",
        "NETWORK_DEGRADATION",
        "ACK_STALL",
        "SOURCE_DIVERGENCE",
        "REFERENCE_UNAVAILABLE",
        "UNDETERMINED",
    ] = "ALIGNED"
    component = "unknown"
    next_check = (
        "Keep comparing source, reference and delivered quotes; no off-market investigation."
    )
    if check.status == "UNKNOWN":
        hypothesis, component = "REFERENCE_UNAVAILABLE", "reference"
        price = "Reference quorum is unavailable; withhold the off-market verdict."
        next_check = "Validate reference freshness, clock uncertainty and contributor independence."
    elif check.classification == "SOURCE_DIVERGENCE":
        hypothesis, component = "SOURCE_DIVERGENCE", "tokyo_source"
        price = (
            "The fresh Tokyo source and NYC quote agree with each other, but "
            "differ from the reference."
        )
        next_check = (
            "Inspect Tokyo quote inputs, instrument mapping and quote basis; "
            "do not assume a TCP fault."
        )
    elif check.classification in {"STALE_DELIVERY", "UNDETERMINED"}:
        price = (
            "Tokyo remains aligned with the reference; the NYC quote is stale "
            "and outside the reference band."
            if check.classification == "STALE_DELIVERY"
            else "The NYC quote is outside the reference band; source and delivery "
            "evidence must be checked."
        )
        hypothesis, component = "UNDETERMINED", "unknown"
        next_check = (
            "Obtain fresh, identity-matched Corvil and CLI snapshots before localizing the cause."
        )
        if technical_fresh and joined:
            if (
                float(queue.metrics["unacked_limit_headroom"]) == 0
                and float(tcp.metrics["transmit_window_bytes"]) > 0
                and float(corvil.metrics["retransmit_pct"]) < 0.5
            ):
                hypothesis, component = "ACK_STALL", "nyc_application"
                next_check = (
                    "Inspect consumer flow 42 acknowledgement policy and processing progress; "
                    "a healthy TCP session does not establish application processing."
                )
            elif (
                float(tcp.metrics["transmit_window_bytes"]) == 0
                and float(corvil.metrics["peer_receive_window_bytes"]) == 0
                and float(corvil.metrics["retransmit_pct"]) < 0.5
            ):
                hypothesis, component = "CONSUMER_BACKPRESSURE", "nyc_consumer"
                next_check = (
                    "Inspect socket reads and processing on 10.30.1.20:43172; compare "
                    "flow 42 and the unaffected consumer before blaming the network."
                )
            elif (
                float(corvil.metrics["retransmit_pct"]) >= 0.5
                and float(tcp.metrics["transmit_window_bytes"]) > 0
                and float(tcp.metrics["timed_retransmit_delta"]) > 0
            ):
                hypothesis, component = "NETWORK_DEGRADATION", "nyc_network"
                next_check = (
                    "Inspect the broker-to-NYC network segment and interface counters; "
                    "compare packet timing and retransmit deltas with the healthy peer."
                )
    if not technical_fresh or not joined:
        broker = (
            "CLI evidence is unavailable, stale or not matched to this "
            "session/flow; cause is unconfirmed."
        )
        if hypothesis == "SOURCE_DIVERGENCE":
            hypothesis, component = "UNDETERMINED", "unknown"
            next_check = (
                "Source/reference divergence is measured; obtain valid CLI "
                "evidence before ruling out transport issues."
            )
    return PathDiagnosis(
        hypothesis=hypothesis,
        suspected_component=component,
        evidence=[
            DiagnosticEvidence(
                source="PRICES", finding=price, evidence_ids=["market", "reference", "data_quality"]
            ),
            DiagnosticEvidence(source="CORVIL", finding=wire, evidence_ids=["corvil_tcp"]),
            DiagnosticEvidence(
                source="BROKER_CLI", finding=broker, evidence_ids=["broker_tcp", "broker_queue"]
            ),
        ],
        next_check=next_check,
        limitations=[
            "Hypotheses, not proven root causes. Corvil and CLI TCP counters can describe "
            "the same fault and are not independent votes.",
            "TCP ACKs, messaging transport ACKs and application settlement are distinct.",
            "CLI blocked percentage uses a recent window (about a minute), not a 1-second gauge.",
            "Unacked-limit headroom is derived from the configured limit and "
            "outstanding count; it is not messaging transport-window credit.",
            "Capture gaps, clock errors, reset counters, broker role or "
            "session changes weaken attribution.",
        ],
    )
