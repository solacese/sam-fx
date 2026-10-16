from datetime import UTC, datetime, timedelta

import pytest

from fx_regime.agent import GroqAgent
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.models import ReferenceQuote
from fx_regime.offmarket import OffMarketDetector
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus

NOW = datetime(2026, 10, 15, 10, tzinfo=UTC)


def quote(name, mid=1.12, age=80, **kwargs):
    return ReferenceQuote(
        contributor=name,
        timestamp=NOW - timedelta(milliseconds=age),
        received_at=NOW - timedelta(milliseconds=5),
        bid=mid - 0.00004,
        ask=mid + 0.00004,
        **kwargs,
    )


def observe(detector, refs=None, delivered=None, source=None, now=NOW):
    return detector.observe(
        now,
        refs or [quote("R1"), quote("R2", 1.120005)],
        delivered or quote("NYC"),
        source or quote("SOURCE"),
    )


def test_one_bad_reference_cannot_move_consensus():
    state = observe(OffMarketDetector(), [quote("R1"), quote("R2", 1.120005), quote("R3", 1.13)])
    assert state.status == "WITHIN_BAND"
    assert state.contributors_used == ["R1", "R2"] and "R3" in state.excluded
    assert state.reference_mid == pytest.approx(1.1200025)


@pytest.mark.parametrize(
    "refs",
    [
        [quote("R1"), quote("R1")],  # duplicates do not supply quorum
        [quote("R1"), quote("R2", age=800)],
        [quote("R1"), quote("R2", age=-20)],
        [quote("R1"), quote("R2", basis="EURUSD-FORWARD")],
        [quote("R1"), quote("R2", symbol="GBPUSD")],
        [quote("R1"), quote("R2", clock_uncertainty_ms=90)],
        [quote("R1", age=10), quote("R2", age=200)],  # fresh but not time-aligned
        [quote("R1"), quote("R2", 1.121)],  # disagreeing sources
    ],
)
def test_invalid_quorum_withholds_verdict(refs):
    state = observe(OffMarketDetector(), refs, delivered=quote("NYC", 1.11))
    assert state.status == "UNKNOWN" and state.mid_delta_pips is None
    assert state.classification == "REFERENCE_UNAVAILABLE"


def test_spread_overlap_is_not_offmarket_and_tolerance_is_beyond_band():
    wide = quote("NYC", 1.1202).model_copy(update={"bid": 1.1199, "ask": 1.1205})
    state = observe(OffMarketDetector(), delivered=wide)
    assert state.outside_band_pips == 0 and state.status == "WITHIN_BAND"
    # A 1.2 pip mid discrepancy is only 0.4 pips beyond these quote bands.
    state = observe(OffMarketDetector(), delivered=quote("NYC", 1.12012))
    assert state.outside_band_pips < 1 and state.status == "WITHIN_BAND"


def test_confirmation_gaps_and_distinct_recovery_observations():
    detector = OffMarketDetector()

    def sample(t, bad):
        when = NOW + timedelta(seconds=t)
        refs = [
            quote("R1").model_copy(
                update={"timestamp": when - timedelta(milliseconds=50), "received_at": when}
            )
        ]
        refs.append(refs[0].model_copy(update={"contributor": "R2"}))
        delivered = refs[0].model_copy(
            update={
                "contributor": "NYC",
                "bid": 1.1100 if bad else 1.11996,
                "ask": 1.11008 if bad else 1.12004,
            }
        )
        return detector.observe(when, refs, delivered, refs[0])

    assert sample(0, True).status == "SUSPECTED"
    with pytest.raises(ValueError):
        sample(0, True)
    assert sample(2, True).consecutive == 1  # clock gap resets votes
    assert sample(3, True).status == "SUSPECTED"
    assert sample(4, True).status == "OFF_MARKET"
    for i in range(5):
        assert sample(5 + i, False).confirmed == (i == 4)


@pytest.mark.parametrize(
    "scenario,status,classification,suspect",
    [
        ("offmarket_stale", "OFF_MARKET", "STALE_DELIVERY", "nyc_consumer"),
        ("offmarket_network", "OFF_MARKET", "STALE_DELIVERY", "nyc_network"),
        ("offmarket_ack", "OFF_MARKET", "STALE_DELIVERY", "nyc_application"),
        ("offmarket_blind", "OFF_MARKET", "STALE_DELIVERY", "unknown"),
        ("offmarket_source", "OFF_MARKET", "SOURCE_DIVERGENCE", "tokyo_source"),
        ("reference_loss", "UNKNOWN", "REFERENCE_UNAVAILABLE", "reference"),
        ("reference_outlier", "WITHIN_BAND", "ALIGNED", None),
        ("market_reprice", "WITHIN_BAND", "ALIGNED", None),
    ],
)
async def test_end_to_end_offmarket_cases_and_recovery(scenario, status, classification, suspect):
    engine = ScenarioEngine(
        RegimeDetector(), JevClient(""), GroqAgent("", "prepared"), SolaceBus(""), tick_seconds=0
    )
    for i in range(10):
        await engine._sample(scenario, i)
    await engine.drain()
    check = engine.state.aiops.offmarket
    assert check.status == status and check.classification == classification
    if suspect:
        a = engine.state.assessment
        assert a.suspected_component == suspect
        assert a.offmarket_at_event.status == status
        assert len(a.graph.nodes) == 5
        assert "reference" in a.evidence_refs and "data_quality" in a.evidence_refs
        assert engine.state.completed_investigations == 1
        if scenario == "offmarket_source":
            assert engine.state.aiops.technical_score == 0
            assert [e.edge_id for e in a.graph.edges] == [
                "reference_data",
                "reference_source",
                "source_data",
            ]
        if scenario == "reference_loss":
            assert not a.graph.edges
        reference_before_recovery = check.reference_mid
        for healthy_index in range(4):
            await engine._sample("baseline", 0)
            if healthy_index == 0 and scenario == "offmarket_stale":
                assert (
                    abs(engine.state.aiops.offmarket.reference_mid - reference_before_recovery)
                    < 0.00002
                )
            assert engine.state.incidents[0].status == "OPEN"
        await engine._sample("baseline", 0)
        assert engine.state.incidents[0].status == "RECOVERED"
        assert a.offmarket_at_event.status == status  # frozen, not recovered numbers
    else:
        assert not engine.state.incidents and engine.agent.calls == 0
    engine.store.db.close()


@pytest.mark.parametrize(
    "scenario,expected_component,bad_component,bad_assessment",
    [
        ("offmarket_source", "tokyo_source", "nyc_tcp", "A TCP fault caused the price error."),
        (
            "offmarket_source",
            "tokyo_source",
            "tokyo_source",
            "The price differs by 6 pips from the reference band.",
        ),
        ("offmarket_blind", "unknown", "nyc_consumer", "The consumer caused the stale price."),
    ],
)
async def test_llm_cannot_override_frozen_comparison(
    monkeypatch, scenario, expected_component, bad_component, bad_assessment
):
    import json
    from types import SimpleNamespace

    engine = ScenarioEngine(
        RegimeDetector(), JevClient(""), GroqAgent("", "prepared"), SolaceBus(""), tick_seconds=0
    )
    for i in range(8):
        await engine._sample(scenario, i)
    await engine.drain()
    if scenario == "offmarket_source":
        assert engine.state.service_condition == "HEALTHY"
    change = engine.state.last_change
    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            calls.append(kwargs)
            tool = {
                "id": "call-1",
                "type": "function",
                "function": {"name": "inspect_fx_path", "arguments": '{"path_id":"TYO-NYC-FX-01"}'},
            }
            result = {
                "assessment": bad_assessment,
                "suspected_component": bad_component,
                "evidence_ids": ["reference", "data_quality"],
                "suggested_next_investigation": "Restart TCP.",
                "hypothesis_edges": ["tcp_queue", "queue_data"],
            }
            message = (
                SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(id="call-1", function=SimpleNamespace(**tool["function"]))
                    ],
                    model_dump=lambda **kw: {"role": "assistant", "tool_calls": [tool]},
                )
                if len(calls) == 1
                else SimpleNamespace(content=json.dumps(result))
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        async def close(self):
            pass

    monkeypatch.setattr("fx_regime.aiops_agent.AsyncGroq", Client)
    assessment = await GroqAgent("key", "test-model").explain(change, JevClient._fallback(change))
    assert len(calls) == 2
    assert assessment.degraded and "fallback" in assessment.model
    assert assessment.suspected_component == expected_component
    assert assessment.offmarket_at_event.status == "OFF_MARKET"
    assert [e.edge_id for e in assessment.graph.edges] == (
        [
            "reference_data",
            "reference_source",
            "source_data",
        ]
        if scenario == "offmarket_source"
        else ["reference_data", "reference_source"]
    )
    engine.store.db.close()
