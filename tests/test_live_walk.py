import asyncio

from fx_regime.agent import GroqAgent
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus


async def test_live_walk_updates_market_every_second_without_ai() -> None:
    jev = JevClient("")
    agent = GroqAgent("", "test-model")
    engine = ScenarioEngine(RegimeDetector(min_baseline_seconds=30), jev, agent, SolaceBus(""))
    await engine.start_live()
    await asyncio.sleep(1.05)
    first = engine.state.snapshot
    await asyncio.sleep(1.05)
    second = engine.state.snapshot
    await engine.stop_live()

    assert first is not None and second is not None
    assert first.timestamp != second.timestamp
    assert first.mid != second.mid
    assert engine.state.observations >= 3
    assert second.values.spread_pips > 0
    assert jev.calls == 0
    assert agent.calls == 0
