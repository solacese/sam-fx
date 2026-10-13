from datetime import UTC, datetime, timedelta

from fx_regime.detector import RegimeDetector
from fx_regime.models import FeatureValues, Regime


def value(**changes: float) -> FeatureValues:
    baseline = {
        "realized_volatility": 0.00002,
        "spread_pips": 0.7,
        "quote_rate": 18,
        "solace_latency_ms": 7,
        "consumer_lag": 0,
    }
    baseline.update(changes)
    return FeatureValues(**baseline)


def update(detector: RegimeDetector, second: int, values: FeatureValues):
    timestamp = datetime(2026, 10, 7, tzinfo=UTC) + timedelta(seconds=second)
    return detector.update(
        symbol="EURUSD",
        timestamp=timestamp,
        bid=1.1781,
        ask=1.1782,
        values=values,
    )


def test_requires_baseline_and_persistence_then_emits_once() -> None:
    detector = RegimeDetector(min_baseline_seconds=10, persistence_seconds=3)
    for second in range(10):
        snapshot, change = update(detector, second, value(spread_pips=0.68 + second % 2 * 0.04))
        assert snapshot.regime == Regime.NORMAL
        assert change is None

    events = []
    for second in range(10, 18):
        _, change = update(
            detector,
            second,
            value(realized_volatility=0.00014, spread_pips=3.2, quote_rate=58),
        )
        if change:
            events.append(change)

    assert len(events) == 1
    assert events[0].previous_regime == Regime.NORMAL
    assert events[0].new_regime == Regime.STRESSED
    assert events[0].drivers.volatility >= 3


def test_hysteresis_requires_sustained_recovery() -> None:
    detector = RegimeDetector(
        min_baseline_seconds=5,
        persistence_seconds=2,
        recovery_seconds=3,
    )
    for second in range(5):
        update(detector, second, value(spread_pips=0.65 + second * 0.02))
    for second in range(5, 13):
        update(detector, second, value(spread_pips=4, quote_rate=65, realized_volatility=0.0002))
    assert detector.regime == Regime.STRESSED

    recovery_event = None
    for second in range(13, 50):
        _, change = update(detector, second, value())
        if change:
            recovery_event = change
            break
    assert recovery_event is not None
    assert recovery_event.new_regime == Regime.NORMAL
    assert second >= 11


def test_duplicate_seconds_cannot_manufacture_persistence():
    import pytest

    detector = RegimeDetector(min_baseline_seconds=5)
    for second in range(5):
        update(detector, second, value())
    update(detector, 5, value(spread_pips=6))
    for _ in range(10):
        with pytest.raises(ValueError):
            update(detector, 5, value(spread_pips=6))
    assert detector.regime == Regime.NORMAL
    with pytest.raises(ValueError):
        update(detector, 4, value())
