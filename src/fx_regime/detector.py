from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from statistics import fmean, median

from .models import (
    DetectionScores,
    FeatureSnapshot,
    FeatureValues,
    FeatureZScores,
    InfraStats,
    MacroEvent,
    Regime,
    RegimeChange,
)

_FIELDS = (
    "realized_volatility",
    "spread_pips",
    "quote_rate",
    "solace_latency_ms",
    "consumer_lag",
)
_FLOORS = {
    "realized_volatility": 0.000002,
    "spread_pips": 0.08,
    "quote_rate": 0.5,
    "solace_latency_ms": 0.5,
    "consumer_lag": 0.5,
}


class RegimeDetector:
    """Rolling, explainable detector with persistence and asymmetric hysteresis."""

    def __init__(
        self,
        *,
        baseline_seconds: int = 300,
        min_baseline_seconds: int = 30,
        persistence_seconds: int = 4,
        recovery_seconds: int = 8,
        entry_score: float = 3.0,
        stressed_score: float = 4.2,
        exit_score: float = 1.25,
    ) -> None:
        self._history: deque[FeatureValues] = deque(maxlen=baseline_seconds)
        self._min_baseline = min_baseline_seconds
        self._persistence = persistence_seconds
        self._recovery = recovery_seconds
        self._entry_score = entry_score
        self._stressed_score = stressed_score
        self._exit_score = exit_score
        self.regime = Regime.NORMAL
        self._candidate = Regime.NORMAL
        self._candidate_count = 0
        self._score_5s: deque[float] = deque(maxlen=5)
        self._score_30s: deque[float] = deque(maxlen=30)
        self._entry_votes: deque[bool] = deque(maxlen=5)
        self._stress_votes: deque[bool] = deque(maxlen=30)
        self._cusum = 0.0
        self._last_timestamp: datetime | None = None

    @property
    def baseline_ready(self) -> bool:
        return len(self._history) >= self._min_baseline

    def update(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        bid: float,
        ask: float,
        values: FeatureValues,
        regions: dict[str, InfraStats] | None = None,
        macro_events: list[MacroEvent] | None = None,
    ) -> tuple[FeatureSnapshot, RegimeChange | None]:
        second = timestamp.replace(microsecond=0)
        if self._last_timestamp is not None:
            if second <= self._last_timestamp:
                raise ValueError("duplicate or out-of-order observation second")
            if (second - self._last_timestamp).total_seconds() != 1:
                self._score_5s.clear()
                self._score_30s.clear()
                self._entry_votes.clear()
                self._stress_votes.clear()
                self._cusum = 0.0
                self._candidate_count = 0
        self._last_timestamp = second
        baseline = self._baseline_values()
        zscores = self._zscores(values)
        instantaneous = self._combined_score(zscores)
        self._score_5s.append(instantaneous)
        self._score_30s.append(instantaneous)
        shock_5s = fmean(self._score_5s)
        persistence_30s = fmean(self._score_30s)
        # Accumulate only materially abnormal evidence. Ordinary 1–2 sigma
        # microstructure variation should decay, not eventually trip CUSUM.
        self._cusum = max(0.0, self._cusum + shock_5s - 2.0)
        if shock_5s < 1.5:
            self._cusum *= 0.35
        market_score = self._market_score(zscores)
        infrastructure_score = self._infrastructure_score(zscores)
        score = round(max(shock_5s, 0.72 * shock_5s + 0.28 * persistence_30s), 2)
        self._entry_votes.append(score >= self._entry_score)
        self._stress_votes.append(score >= 3.5)
        desired = self._desired_regime(score, persistence_30s)
        previous = self.regime

        if desired == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = desired
            self._candidate_count = 1

        required = self._recovery if desired == Regime.NORMAL else min(self._persistence, 2)
        if self.baseline_ready and desired != self.regime and self._candidate_count >= required:
            self.regime = desired
            self._candidate_count = 0

        snapshot = FeatureSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2,
            values=values,
            zscores=zscores,
            combined_score=score,
            detection=DetectionScores(
                shock_5s=round(shock_5s, 2),
                persistence_30s=round(persistence_30s, 2),
                market=round(market_score, 2),
                infrastructure=round(infrastructure_score, 2),
                cusum=round(self._cusum, 2),
            ),
            regime=self.regime,
            candidate_regime=self._candidate,
            persistence_seconds=self._candidate_count,
        )
        change = None
        if self.regime != previous:
            change = RegimeChange(
                symbol=symbol,
                timestamp=timestamp,
                previous_regime=previous,
                new_regime=self.regime,
                drivers=zscores,
                combined_score=score,
                detection=snapshot.detection,
                before=baseline,
                after=values,
                regions=regions or {},
                macro_events=macro_events or [],
            )

        # Keep confirmed/candidate anomalies out of the adaptive baseline. Otherwise a
        # sustained shock teaches the detector that the shock is normal before the
        # persistence gate can fire.
        if desired == Regime.NORMAL:
            self._history.append(values)
        return snapshot, change

    def _desired_regime(self, score: float, persistence_30s: float) -> Regime:
        if self.regime != Regime.NORMAL and score <= self._exit_score and persistence_30s < 1.0:
            return Regime.NORMAL
        if self.regime != Regime.NORMAL and score < self._entry_score:
            return self.regime
        fast_confirmed = sum(self._entry_votes) >= 4 or self._cusum >= 5.0
        stressed_confirmed = sum(self._stress_votes) >= 20 or self._cusum >= 5.0
        if score >= self._stressed_score and stressed_confirmed:
            return Regime.STRESSED
        if fast_confirmed and score >= 2.2:
            return Regime.VOLATILE
        return Regime.NORMAL

    def _baseline_values(self) -> FeatureValues:
        if not self._history:
            return FeatureValues()
        return FeatureValues(
            **{field: fmean(getattr(row, field) for row in self._history) for field in _FIELDS}
        )

    def _zscores(self, current: FeatureValues) -> FeatureZScores:
        if not self.baseline_ready:
            return FeatureZScores()
        scores: dict[str, float] = {}
        for field in _FIELDS:
            samples = [getattr(row, field) for row in self._history]
            center = median(samples)
            mad = median(abs(sample - center) for sample in samples)
            robust_sigma = max(1.4826 * mad, _FLOORS[field])
            scores[field] = max(0.0, min(6.0, (getattr(current, field) - center) / robust_sigma))
        return FeatureZScores(
            volatility=round(scores["realized_volatility"], 2),
            spread=round(scores["spread_pips"], 2),
            quote_rate=round(scores["quote_rate"], 2),
            solace_latency=round(scores["solace_latency_ms"], 2),
            consumer_lag=round(scores["consumer_lag"], 2),
        )

    @staticmethod
    def _market_score(scores: FeatureZScores) -> float:
        return 0.45 * scores.volatility + 0.30 * scores.spread + 0.25 * scores.quote_rate

    @staticmethod
    def _infrastructure_score(scores: FeatureZScores) -> float:
        return 0.55 * scores.solace_latency + 0.45 * scores.consumer_lag

    @classmethod
    def _combined_score(cls, scores: FeatureZScores) -> float:
        market = cls._market_score(scores)
        infrastructure = cls._infrastructure_score(scores)
        peak = max(
            scores.volatility,
            scores.spread,
            scores.quote_rate,
            scores.solace_latency,
            scores.consumer_lag,
        )
        return round(max(market, infrastructure, 0.7 * market + 0.5 * infrastructure, peak), 2)

    def reset(self) -> None:
        self._last_timestamp = None
        self._history.clear()
        self.regime = Regime.NORMAL
        self._candidate = Regime.NORMAL
        self._candidate_count = 0
        self._score_5s.clear()
        self._score_30s.clear()
        self._entry_votes.clear()
        self._stress_votes.clear()
        self._cusum = 0.0


def relative_change(before: float, after: float) -> str:
    if math.isclose(before, 0.0):
        return "newly elevated"
    return f"{after / before:.1f}×"
