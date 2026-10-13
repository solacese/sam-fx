from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from .models import FeatureValues, InfraStats, MarketTick


@dataclass
class SecondBucket:
    timestamp: datetime
    ticks: list[MarketTick] = field(default_factory=list)


class FeatureEngine:
    """Turns raw quotes into one-second numeric features without calling any model."""

    def __init__(self) -> None:
        self._bucket: SecondBucket | None = None
        self._returns: deque[float] = deque(maxlen=5)
        self._last_mid: float | None = None

    def add_tick(self, tick: MarketTick) -> FeatureValues | None:
        second = tick.timestamp.replace(microsecond=0)
        if self._bucket is None:
            self._bucket = SecondBucket(second, [tick])
            return None
        if second == self._bucket.timestamp:
            self._bucket.ticks.append(tick)
            return None
        completed = self._complete(self._bucket)
        self._bucket = SecondBucket(second, [tick])
        return completed

    def flush(self) -> FeatureValues | None:
        if self._bucket is None:
            return None
        completed = self._complete(self._bucket)
        self._bucket = None
        return completed

    def _complete(self, bucket: SecondBucket) -> FeatureValues:
        last = bucket.ticks[-1]
        mid = (last.bid + last.ask) / 2
        if self._last_mid and self._last_mid > 0:
            self._returns.append(math.log(mid / self._last_mid))
        self._last_mid = mid
        volatility = math.sqrt(sum(value * value for value in self._returns))
        spread_pips = max(0.0, (last.ask - last.bid) * 10_000)
        latency = max(
            0.0,
            (datetime.now(last.timestamp.tzinfo) - last.timestamp).total_seconds() * 1_000,
        )
        return FeatureValues(
            realized_volatility=volatility,
            spread_pips=spread_pips,
            quote_rate=float(len(bucket.ticks)),
            solace_latency_ms=latency,
            consumer_lag=0,
        )


def merge_infrastructure(values: FeatureValues, stats: list[InfraStats]) -> FeatureValues:
    if not stats:
        return values
    return values.model_copy(
        update={
            "solace_latency_ms": max(item.latency_ms for item in stats),
            "consumer_lag": float(max(item.consumer_lag for item in stats)),
        }
    )
