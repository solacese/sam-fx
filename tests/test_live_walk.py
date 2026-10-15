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


async def test_price_history_is_bounded_and_matches_source_quotes() -> None:
    engine = ScenarioEngine(RegimeDetector(), JevClient(""), GroqAgent("", "test"), SolaceBus(""))
    for _ in range(305):
        await engine._sample("baseline", 0)
    points = engine.state.price_history
    snapshot = engine.state.snapshot
    assert len(points) == 301
    assert snapshot is not None
    assert points[-1].timestamp == snapshot.timestamp
    assert points[-1].mid == snapshot.mid
    assert points[-1].bid == snapshot.bid
    assert points[-1].ask == snapshot.ask
    assert all(a.timestamp < b.timestamp for a, b in zip(points, points[1:], strict=False))
    assert all(abs(p.mid - (p.bid + p.ask) / 2) < 1e-12 for p in points)
    engine.store.db.close()
