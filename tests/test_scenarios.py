import asyncio

import pytest

from fx_regime.agent import GroqAgent
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.models import Cause, FeatureValues
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus


@pytest.mark.parametrize(
    ("scenario", "cause"),
    [
        ("volatile", Cause.MARKET),
        ("spread", Cause.MARKET),
        ("market", Cause.MARKET),
        ("infrastructure", Cause.INFRASTRUCTURE),
    ],
)
async def test_scenario_produces_expected_assessment(scenario: str, cause: Cause) -> None:
    detector = RegimeDetector(min_baseline_seconds=30, persistence_seconds=4)
    jev = JevClient("")
    agent = GroqAgent("", "test-model")
    engine = ScenarioEngine(detector, jev, agent, SolaceBus(""), tick_seconds=0)

    await engine.start(scenario)
    assert engine._task is not None
    await engine._task
    await engine.drain()

    assert engine.state.assessment is not None
    assert engine.state.assessment.likely_cause == cause
    assert engine.state.last_change is not None
    if scenario != "infrastructure":
        assert engine.state.last_change.combined_score >= 4.2
    else:
        assert engine.state.last_change.event == "FX_SERVICE_INCIDENT"
    if scenario == "volatile":
        assert engine.state.last_change.drivers.volatility >= 4.5
        assert engine.state.last_change.after.spread_pips <= 1.0
    elif scenario == "spread":
        assert engine.state.last_change.drivers.spread >= 4.5
        assert engine.state.last_change.after.spread_pips >= 5.0
    elif scenario == "market":
        assert engine.state.last_change.drivers.volatility >= 4.5
        assert engine.state.last_change.drivers.spread >= 4.5
        assert engine.state.last_change.after.quote_rate >= 70
    else:
        assert engine.state.last_change.drivers.solace_latency >= 4.5
        assert engine.state.last_change.after.consumer_lag >= 100
    assert jev.calls == 1
    assert agent.calls == 1


async def test_raw_updates_never_call_ai() -> None:
    detector = RegimeDetector(min_baseline_seconds=3, persistence_seconds=2)
    jev = JevClient("")
    agent = GroqAgent("", "test-model")
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    for second in range(20):
        detector.update(
            symbol="EURUSD",
            timestamp=now + __import__("datetime").timedelta(seconds=second),
            bid=1.1781,
            ask=1.1782,
            values=FeatureValues(
                realized_volatility=0.00002,
                spread_pips=0.7,
                quote_rate=18,
                solace_latency_ms=7,
                consumer_lag=0,
            ),
        )
    await asyncio.sleep(0)
    assert jev.calls == 0
    assert agent.calls == 0
