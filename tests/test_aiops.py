from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fx_regime.agent import GroqAgent
from fx_regime.aiops import ConfidenceMonitor, explanation_graph
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.models import FeatureValues
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus


def observe(scenario, count=12):
    monitor = ConfidenceMonitor()
    now = datetime.now(UTC).replace(microsecond=0)
    frames = [
        monitor.observe(scenario, i, now + timedelta(seconds=i), FeatureValues(quote_rate=18))
        for i in range(count)
    ]
    return monitor, now, frames


def test_market_activity_alone_preserves_confidence():
    _, _, frames = observe("market_only")
    assert all(f.status == "WITHIN_LIMITS" and f.technical_score == 0 for f in frames)
    assert frames[-1].market_regime == "STRESSED"


def test_multi_source_confidence_confirmation_and_recovery():
    monitor, now, frames = observe("tokyo_burst")
    assert frames[0].status == "WITHIN_LIMITS"
    assert frames[2].status == "WATCH"
    assert frames[4].status == "AT_RISK" and frames[4].confirmed
    assert frames[-1].status == "IMPAIRED"
    assert [s.change_offset_s for s in frames[4].sources] == [0, 2, 2, 3, 4]
    assert {s.source for s in frames[-1].sources} >= {"MARKET", "CORVIL", "BROKER_CLI"}
    for i in range(5):
        healthy = monitor.observe("baseline", 0, now + timedelta(seconds=12 + i), FeatureValues())
        assert healthy.confirmed == (i == 4)
    assert healthy.status == "WITHIN_LIMITS"


def test_unknown_and_gap_do_not_create_false_confirmation():
    monitor, now, frames = observe("aiops_unknown", 2)
    assert frames[-1].status == "UNKNOWN" and not frames[-1].confirmed
    gap = monitor.observe("aiops_unknown", 2, now + timedelta(seconds=5), FeatureValues())
    assert gap.confirmation_count == 1 and not gap.confirmed
    assert not explanation_graph(gap, ["market_tcp", "tcp_queue"]).edges


async def event(scenario="tokyo_burst"):
    engine = ScenarioEngine(
        RegimeDetector(), JevClient(""), GroqAgent("", "test"), SolaceBus(""), tick_seconds=0
    )
    for i in range(10):
        await engine._sample(scenario, i)
    await engine.drain()
    return engine


@pytest.mark.parametrize(
    "scenario,suspect",
    [
        ("tokyo_burst", "nyc_tcp"),
        ("tcp_pressure", "nyc_tcp"),
        ("queue_pressure", "nyc_queue"),
        ("aiops_unknown", "unknown"),
    ],
)
async def test_one_investigation_per_confirmed_episode(scenario, suspect):
    engine = await event(scenario)
    assert engine.state.completed_investigations == 1
    assert len(engine.state.incidents) == 1
    assessment = engine.state.assessment
    assert assessment.suspected_component == suspect
    assert assessment.model == "deterministic-fallback"
    assert len(assessment.checks) == 3
    assert engine.state.last_change.event == "FX_DATA_CONFIDENCE_CHANGE"
    assert engine.state.last_change.aiops.timestamp < engine.state.aiops.timestamp
    assert all(e.kind in {"hypothesis", "sequence"} for e in assessment.graph.edges)
    if scenario in {"tcp_pressure", "queue_pressure"}:
        assert "market_tcp" not in [e.edge_id for e in assessment.graph.edges]
    if scenario == "queue_pressure":
        assert [e.edge_id for e in assessment.graph.edges] == ["queue_data"]
    engine.store.db.close()


async def test_market_only_never_wakes_the_investigator():
    engine = await event("market_only")
    assert not engine.state.incidents and not engine.state.assessment
    assert engine.agent.calls == 0
    assert engine.state.aiops.status == "WITHIN_LIMITS"
    engine.store.db.close()


async def test_llm_must_call_scoped_tool_and_use_known_evidence(monkeypatch):
    engine = await event()
    change = engine.state.last_change
    calls = []

    class Message:
        tool_calls = [
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(
                    name="inspect_fx_path", arguments='{"path_id":"TYO-NYC-FX-01"}'
                ),
            )
        ]

        def model_dump(self, **kwargs):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "inspect_fx_path",
                            "arguments": '{"path_id":"TYO-NYC-FX-01"}',
                        },
                    }
                ],
            }

    class Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = (
                Message()
                if len(calls) == 1
                else SimpleNamespace(
                    content=(
                        '{"assessment":"Greg, suspect NYC receiver backpressure.",'
                        '"suspected_component":"nyc_tcp","evidence_ids":["corvil_tcp","broker_tcp"],'
                        '"suggested_next_investigation":"Compare the peer.",'
                        '"hypothesis_edges":["market_tcp","tcp_queue","queue_data"]}'
                    )
                )
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class Client:
        chat = SimpleNamespace(completions=Completions())

        async def close(self):
            pass

    monkeypatch.setattr("fx_regime.aiops_agent.AsyncGroq", lambda **kwargs: Client())
    result = await GroqAgent("key", "test-model").explain(change, JevClient._fallback(change))
    assert len(calls) == 2 and not result.degraded
    assert calls[0]["tool_choice"]["function"]["name"] == "inspect_fx_path"
    assert any(m["role"] == "tool" and "43172" in m["content"] for m in calls[1]["messages"])
    assert result.evidence_refs == ["corvil_tcp", "broker_tcp"]
    assert result.suspected_component == "nyc_tcp"
    engine.store.db.close()


async def test_provider_failure_is_visible_and_keeps_graph(monkeypatch):
    engine = await event()

    class Broken:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            raise ValueError("invalid provider output")

        async def close(self):
            pass

    monkeypatch.setattr("fx_regime.aiops_agent.AsyncGroq", Broken)
    change = engine.state.last_change
    result = await GroqAgent("key", "model").explain(change, JevClient._fallback(change))
    assert result.degraded and "fallback" in result.model
    assert result.graph and result.checks
    engine.store.db.close()
