import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fx_regime.agent import GroqAgent
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.models import Cause, FeatureValues, MarketTick, ServiceObservation
from fx_regime.operations import ServiceMonitor
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus
from fx_regime.store import IncidentStore


def engine(**kwargs):
    return ScenarioEngine(
        RegimeDetector(),
        JevClient(""),
        GroqAgent("", "test"),
        SolaceBus(""),
        tick_seconds=0,
        **kwargs,
    )


async def run(e, scenario):
    await e.start(scenario)
    await e._task
    await e.drain()


@pytest.mark.parametrize(
    ("scenario", "health", "cause"),
    [
        ("feed_loss", "UNAVAILABLE", Cause.INFRASTRUCTURE),
        ("telemetry_loss", "UNKNOWN", Cause.UNCLEAR),
        ("capacity", "DEGRADED", Cause.BOTH),
    ],
)
async def test_service_incident_independent_of_market(scenario, health, cause):
    e = engine()
    await run(e, scenario)
    assert e.state.service_condition == health
    assert len(e.state.incidents) == 1
    assert e.state.assessment.likely_cause == cause
    assert e.jev.calls == e.agent.calls == 1
    assert e.state.incidents[0].assessment is not None
    if scenario != "capacity":
        assert e.state.market_condition == "NORMAL"
        assert e.state.last_change.combined_score < 4.2
    if scenario == "telemetry_loss":
        assert "unknown" in e.state.incidents[0].impact.lower()
        assert e.state.incidents[0].severity == "P3"


async def test_market_move_is_advisory_not_incident():
    e = engine()
    await run(e, "market")
    assert not e.state.incidents
    assert e.state.service_condition == "HEALTHY"
    assert e.state.assessment.likely_cause == Cause.MARKET


async def test_acknowledge_recovery_and_resolution():
    e = engine()
    await run(e, "feed_loss")
    incident = e.state.incidents[0]
    await e.incident_action(incident.incident_id, "acknowledge")
    assert e.state.incidents[0].status == "ACKNOWLEDGED"
    with pytest.raises(ValueError):
        await e.incident_action(incident.incident_id, "resolve")
    for _ in range(4):
        await e._sample("baseline", 0)
    assert e.state.incidents[0].status == "ACKNOWLEDGED"
    await e._sample("baseline", 0)
    assert e.state.incidents[0].status == "RECOVERED"
    await e.incident_action(incident.incident_id, "resolve")
    assert e.store.handover()["incidents"][0]["status"] == "RESOLVED"
    await run(e, "feed_loss")
    assert len(e.state.incidents) == 2  # A separate episode gets a new ID.


async def test_slow_provider_does_not_block_sampling(monkeypatch):
    e = engine(investigation_timeout=1)
    entered, release = asyncio.Event(), asyncio.Event()
    original = e.agent.explain

    async def slow(change, decisions):
        entered.set()
        await release.wait()
        return await original(change, decisions)

    monkeypatch.setattr(e.agent, "explain", slow)
    await e.start("feed_loss")
    await entered.wait()
    count = e.state.observations
    await e._task
    assert e.state.observations > count
    assert e.state.pending_investigations == 1
    release.set()
    await e.drain()
    assert e.state.pending_investigations == 0


async def test_provider_deadline_keeps_incident_evidence(monkeypatch):
    e = engine(investigation_timeout=0.01)

    async def hung(change):
        await asyncio.Event().wait()

    monkeypatch.setattr(e.jev, "classify", hung)
    await run(e, "feed_loss")
    assert e.state.assessment.degraded
    assert e.state.assessment.model == "deadline-fallback"
    assert e.state.assessment.likely_cause == Cause.INFRASTRUCTURE
    assert e.store.pending() == 0


async def test_journal_restarts_unfinished_work_and_deduplicates(tmp_path):
    e = engine()
    await run(e, "feed_loss")
    change = e.state.last_change
    path = str(tmp_path / "incidents.db")
    store = IncidentStore(path)
    assert store.enqueue(change, e.state.incidents[0])
    assert not store.enqueue(change)
    assert store.claim() is not None  # Simulate a crash with a running job.
    store.db.close()
    reopened = IncidentStore(path)
    e2 = engine(store=reopened)
    await e2.drain()
    assert reopened.pending() == 0
    assert reopened.incidents()[0].assessment.correlation_id == change.correlation_id
    assert reopened.claim() is None
    reopened.db.close()


async def test_failed_work_is_bounded_and_visible(monkeypatch):
    e = engine()

    async def broken(change):
        raise RuntimeError("provider failure")

    monkeypatch.setattr(e.jev, "classify", broken)
    await run(e, "feed_loss")
    assert e.store.pending() == 0
    assert e.store.handover()["failed_investigations"] == 1
    assert len(e.state.incidents) == 1
    assert e.state.incidents[0].evidence


def test_monitor_rejects_duplicates_and_requires_consecutive_seconds():
    monitor = ServiceMonitor()
    now = datetime.now(UTC).replace(microsecond=0)

    def observe(second):
        timestamp = now + timedelta(seconds=second)
        return monitor.update(
            timestamp,
            [
                ServiceObservation(
                    service_id="a",
                    region="region-a",
                    owner="demo",
                    timestamp=timestamp,
                    connected=False,
                )
            ],
        )[0]

    assert not observe(0).confirmed
    with pytest.raises(ValueError):
        observe(0)
    assert not observe(1).confirmed
    assert not observe(9).confirmed
    assert not observe(10).confirmed
    assert observe(11).confirmed


def test_missing_service_cannot_recover():
    now = datetime.now(UTC)
    monitor = ServiceMonitor()
    monitor.update(
        now,
        [
            ServiceObservation(
                service_id="a", region="A", owner="demo", timestamp=now, connected=False
            )
        ],
    )
    for i in range(1, 8):
        result = monitor.update(now + timedelta(seconds=i), [])
    assert result[0].status == "UNKNOWN"
    assert result[0].confirmed


def test_invalid_quotes_and_features_rejected():
    for bid, ask in [(0, 1), (1.2, 1.1), (float("nan"), 1)]:
        with pytest.raises(ValidationError):
            MarketTick(bid=bid, ask=ask)
    with pytest.raises(ValidationError):
        FeatureValues(quote_rate=float("inf"))


async def test_grounded_fallback_does_not_invent_regions():
    e = engine()
    await run(e, "infrastructure")
    change = e.state.last_change.model_copy(update={"services": [], "regions": {}})
    result = GroqAgent._fallback(change, JevClient._fallback(change), "deterministic-fallback")
    text = result.model_dump_json()
    assert "London" not in text and "New York" not in text and "ECB" not in text
    assert "not supplied" in text


def test_invalid_classifier_choice_is_rejected():
    with pytest.raises(ValueError):
        JevClient._parse({"answers": {"evidence_class": {"choice": "TRADE_NOW"}}})


async def test_market_fallback_does_not_assert_missing_service_health():
    e = engine()
    await run(e, "market")
    change = e.state.last_change.model_copy(update={"services": [], "regions": {}})
    result = GroqAgent._fallback(change, JevClient._fallback(change), "deterministic-fallback")
    assert "Service health is not established" in result.assessment
