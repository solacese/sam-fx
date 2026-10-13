from datetime import UTC, datetime

import pytest

from fx_regime.agent import GroqAgent
from fx_regime.models import (
    Cause,
    FeatureValues,
    FeatureZScores,
    JevDecision,
    Regime,
    RegimeChange,
)


async def test_typed_jev_cause_is_authoritative(monkeypatch: pytest.MonkeyPatch) -> None:
    class Message:
        content = (
            '{"assessment":"mixed","evidence":["latency"],'
            '"likely_cause":"BOTH","suggested_next_investigation":"inspect"}'
        )

    class Completion:
        choices = [type("Choice", (), {"message": Message()})]

    class Completions:
        async def create(self, **kwargs):
            return Completion()

    class Client:
        chat = type("Chat", (), {"completions": Completions()})()

        async def close(self):
            pass

    monkeypatch.setattr("fx_regime.agent.AsyncGroq", lambda **kwargs: Client())
    change = RegimeChange(
        symbol="EURUSD",
        timestamp=datetime.now(UTC),
        previous_regime=Regime.NORMAL,
        new_regime=Regime.STRESSED,
        drivers=FeatureZScores(solace_latency=7, consumer_lag=8),
        combined_score=8,
        before=FeatureValues(),
        after=FeatureValues(),
        regions={},
    )
    result = await GroqAgent("key", "model").explain(
        change,
        [JevDecision(question="EVIDENCE_CLASS", answer="INFRASTRUCTURE", confidence=0.8)],
    )
    assert result.likely_cause == Cause.INFRASTRUCTURE
