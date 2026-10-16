from datetime import UTC, datetime, timedelta

import pytest

from fx_regime.aiops import CONNECTION, ConfidenceMonitor, explanation_graph
from fx_regime.broker_cli import command_pack, diagnose
from fx_regime.models import FeatureValues, SourceEvidence


def fixture(scenario):
    monitor = ConfidenceMonitor()
    start = datetime(2026, 10, 16, 10, tzinfo=UTC)
    for i in range(8):
        state = monitor.observe(
            scenario, i, start + timedelta(seconds=i), FeatureValues(quote_rate=180)
        )
    return state


@pytest.mark.parametrize(
    "scenario,hypothesis,component",
    [
        ("offmarket_stale", "CONSUMER_BACKPRESSURE", "nyc_consumer"),
        ("offmarket_network", "NETWORK_DEGRADATION", "nyc_network"),
        ("offmarket_ack", "ACK_STALL", "nyc_application"),
        ("offmarket_blind", "UNDETERMINED", "unknown"),
        ("offmarket_source", "SOURCE_DIVERGENCE", "tokyo_source"),
    ],
)
def test_cross_source_diagnoses(scenario, hypothesis, component):
    state = fixture(scenario)
    assert state.offmarket.status == "OFF_MARKET"
    assert (
        state.diagnosis.hypothesis == hypothesis
        and state.diagnosis.suspected_component == component
    )
    assert [e.source for e in state.diagnosis.evidence] == ["PRICES", "CORVIL", "BROKER_CLI"]
    if scenario == "offmarket_ack":
        data = {s.evidence_id: s.metrics for s in state.sources}
        assert data["broker_tcp"]["transmit_window_bytes"] > 0
        assert data["broker_queue"]["unacked_limit_headroom"] == 0
        assert [
            e.edge_id
            for e in explanation_graph(state, ["tcp_queue", "queue_data"]).edges
            if e.kind == "hypothesis"
        ] == ["queue_data"]
    if scenario == "offmarket_blind":
        assert not [
            e
            for e in explanation_graph(state, ["tcp_queue", "queue_data"]).edges
            if e.kind == "hypothesis"
        ]


@pytest.mark.parametrize(
    "fault",
    [
        "role",
        "epoch",
        "endpoint",
        "age",
        "counter_reset",
        "capture_drop",
        "clock",
        "unsupported",
        "cli_age",
    ],
)
def test_bad_technical_evidence_does_not_remove_price_verdict_or_invent_cause(fault):
    state = fixture("offmarket_network")
    corvil = next(s for s in state.sources if s.evidence_id == "corvil_tcp")
    tcp = next(s for s in state.sources if s.evidence_id == "broker_tcp")
    cli = state.broker_cli
    if fault == "role":
        cli.ad_role = "AD_STANDBY"
    if fault == "epoch":
        cli.connection_epoch = "different-session"
    if fault == "endpoint":
        corvil.metrics["remote_endpoint"] = "10.99.99.99:12345"
    if fault == "age":
        tcp.timestamp -= timedelta(seconds=11)
    if fault == "counter_reset":
        tcp.metrics["timed_retransmit_delta"] = -1
    if fault == "capture_drop":
        corvil.metrics["capture_drops"] = 25
    if fault == "clock":
        corvil.metrics["capture_clock_uncertainty_us"] = 5000
    if fault == "unsupported":
        cli.captures[0].status = "UNSUPPORTED"
    if fault == "cli_age":
        cli.sampled_at -= timedelta(seconds=11)
    result = diagnose(state)
    assert state.offmarket.status == "OFF_MARKET"
    assert result.hypothesis == "UNDETERMINED" and result.suspected_component == "unknown"


def test_blocked_percentage_is_rolling_and_app_credit_is_not_tcp_window():
    state = fixture("offmarket_stale")
    tcp = next(s for s in state.sources if s.evidence_id == "broker_tcp").metrics
    queue = next(s for s in state.sources if s.evidence_id == "broker_queue").metrics
    assert tcp["blocked_window_seconds"] == 60
    assert tcp["blocked_pct"] == pytest.approx(6 / 60 * 100)
    assert tcp["transmit_window_bytes"] == 0 and queue["unacked_limit_headroom"] > 0
    assert tcp["fast_retransmit_delta"] == 0  # closed receiver, not a loss scenario


@pytest.mark.parametrize(
    "bad", ["*", "foo; reboot", "foo\nshow version", "foo | more", "$(reboot)"]
)
def test_commands_are_exact_scope_read_only(bad):
    with pytest.raises(ValueError):
        command_pack({**CONNECTION, "client_id": bad})
    commands = command_pack(CONNECTION)
    assert all(c.startswith("show ") for c in commands.values())
    assert not any("clear" in c or "*" in c or "enable" in c for c in commands.values())
    assert "FX-PRICE-NYC-01 message-vpn fx-demo connections wide" in commands["tcp"]


def test_historical_semp_evidence_is_readable_without_creating_new_semp_events():
    old = {
        "evidence_id": "semp_tcp",
        "source": "SEMP_V1",
        "timestamp": datetime.now(UTC),
        "region": "NEW_YORK",
        "summary": "Historical record",
        "metrics": {"srtt_us": 1200},
    }
    parsed = SourceEvidence.model_validate(old)
    assert parsed.source == "BROKER_CLI" and parsed.evidence_id == "broker_tcp"
