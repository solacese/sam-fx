from datetime import UTC, datetime

from fx_regime.jev import JevClient
from fx_regime.models import FeatureValues, FeatureZScores, Regime, RegimeChange


def change(zscores: FeatureZScores) -> RegimeChange:
    return RegimeChange(
        symbol="EURUSD",
        timestamp=datetime.now(UTC),
        previous_regime=Regime.NORMAL,
        new_regime=Regime.STRESSED,
        drivers=zscores,
        combined_score=5,
        before=FeatureValues(
            realized_volatility=0.00002,
            spread_pips=0.7,
            quote_rate=18,
            solace_latency_ms=7,
            consumer_lag=0,
        ),
        after=FeatureValues(),
        regions={},
    )


def test_parses_typed_choice_answers() -> None:
    decisions = JevClient._parse(
        {
            "answers": {
                "evidence_class": {
                    "type": "choice",
                    "choice": "MARKET",
                    "confidence": 0.91,
                    "probabilities": {"MARKET": 0.91, "UNCLEAR": 0.09},
                }
            }
        }
    )
    assert decisions[0].question == "EVIDENCE_CLASS"
    assert decisions[0].answer == "MARKET"
    assert decisions[0].confidence == 0.91


def test_fallback_separates_market_and_infrastructure() -> None:
    market = JevClient._fallback(change(FeatureZScores(volatility=5, spread=4, quote_rate=6)))
    infra = JevClient._fallback(
        change(FeatureZScores(solace_latency=5, consumer_lag=6, volatility=0.5))
    )
    assert market[-1].answer == "MARKET"
    assert infra[-1].answer == "INFRASTRUCTURE"
