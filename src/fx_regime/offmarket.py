"""Deterministic comparison of indicative, like-for-like FX quotes.

An illustrative reference band, not fair value or an executable/arbitrage test.
The adapters are synthetic; production needs independent entitlements and clock quality.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations
from statistics import median
from typing import Literal

from .models import OffMarketState, ReferenceQuote

OFFMARKET_SCENARIOS = {
    "offmarket_stale",
    "offmarket_source",
    "reference_loss",
    "reference_outlier",
    "market_reprice",
    "offmarket_network",
    "offmarket_ack",
    "offmarket_blind",
}


class OffMarketDetector:
    """At least two distinct, agreeing, fresh contributors; three distinct-second votes."""

    def __init__(self) -> None:
        self.last: datetime | None = None
        self.votes = 0
        self.recovery = 0
        self.previous_bad: str | None = None

    def observe(
        self,
        now: datetime,
        references: list[ReferenceQuote],
        delivered: ReferenceQuote,
        source: ReferenceQuote,
    ) -> OffMarketState:
        if self.last and now <= self.last:
            raise ValueError("duplicate or out-of-order quote comparison")
        if self.last and (now - self.last).total_seconds() != 1:
            self.votes = self.recovery = 0
        self.last = now
        eligible: dict[str, ReferenceQuote] = {}
        excluded = {}
        for quote in references:
            age = (now - quote.timestamp).total_seconds() * 1000
            receipt_age = (now - quote.received_at).total_seconds() * 1000
            reason = (
                "Different instrument or quote basis"
                if quote.symbol != delivered.symbol or quote.basis != delivered.basis
                else "Clock uncertainty exceeds 20 ms"
                if quote.clock_uncertainty_ms > 20
                else "Stale or future source timestamp"
                if not 0 <= age <= 500
                else "Invalid receipt timestamp"
                if not 0 <= receipt_age <= 500 or quote.timestamp > quote.received_at
                else "Duplicate contributor"
                if quote.contributor in eligible
                else None
            )
            if reason:
                excluded[quote.contributor] = reason
            else:
                eligible[quote.contributor] = quote
        # Largest agreeing cluster, not a single trusted vendor. One outlier cannot move the band.
        candidates = list(eligible.values())
        used: list[ReferenceQuote] = []
        for size in range(len(candidates), 1, -1):
            groups = [
                list(group)
                for group in combinations(candidates, size)
                if (
                    max((q.bid + q.ask) / 2 for q in group)
                    - min((q.bid + q.ask) / 2 for q in group)
                )
                * 10000
                <= 0.5 + 1e-8
                and (
                    max(q.timestamp for q in group) - min(q.timestamp for q in group)
                ).total_seconds()
                <= 0.1
            ]
            if groups:
                used = groups[0]
                break
        valid = (
            len(used) >= 2 and source.symbol == delivered.symbol and source.basis == delivered.basis
        )
        if (
            source.clock_uncertainty_ms > 20
            or delivered.clock_uncertainty_ms > 20
            or delivered.timestamp > now
            or delivered.timestamp > delivered.received_at
            or delivered.received_at > now
        ):
            valid = False
        for name in eligible:
            if name not in {q.contributor for q in used}:
                excluded[name] = "Disagrees with reference cluster or timestamps not aligned"
        ref_bid = median(q.bid for q in used) if valid else None
        ref_ask = median(q.ask for q in used) if valid else None
        ref_mid = (ref_bid + ref_ask) / 2 if ref_bid is not None and ref_ask is not None else None
        mid, source_mid = (delivered.bid + delivered.ask) / 2, (source.bid + source.ask) / 2
        delta = (mid - ref_mid) * 10000 if ref_mid is not None else None
        source_delta = (source_mid - ref_mid) * 10000 if ref_mid is not None else None
        # Separation of quote bands: widening spreads by itself does not trigger a discrepancy.
        outside = (
            max(0.0, (delivered.bid - ref_ask) * 10000, (ref_bid - delivered.ask) * 10000)
            if ref_bid is not None and ref_ask is not None
            else None
        )
        abnormal = outside is not None and outside >= 1.0 - 1e-8
        bad = "unknown" if not valid else "offmarket" if abnormal else None
        self.votes = self.votes + 1 if bad and bad == self.previous_bad else 1 if bad else 0
        self.previous_bad = bad
        self.recovery = 0 if bad else self.recovery + 1
        status: Literal["WITHIN_BAND", "SUSPECTED", "OFF_MARKET", "UNKNOWN"] = (
            "UNKNOWN"
            if not valid
            else "OFF_MARKET"
            if abnormal and self.votes >= 3
            else ("SUSPECTED" if abnormal else "WITHIN_BAND")
        )
        age = max(0.0, (now - delivered.timestamp).total_seconds() * 1000)
        source_age = (now - source.timestamp).total_seconds() * 1000
        classification: Literal[
            "ALIGNED",
            "STALE_DELIVERY",
            "SOURCE_DIVERGENCE",
            "UNDETERMINED",
            "REFERENCE_UNAVAILABLE",
        ] = (
            "REFERENCE_UNAVAILABLE"
            if not valid
            else "ALIGNED"
            if not abnormal
            else "SOURCE_DIVERGENCE"
            if source_delta is not None and abs(source_delta) >= 1.5 and 0 <= source_age <= 500
            else "STALE_DELIVERY"
            if age > 500
            and source_delta is not None
            and abs(source_delta) < 0.5
            and 0 <= source_age <= 500
            else "UNDETERMINED"
        )
        reasons = (
            [
                "Fewer than two fresh, time-aligned, agreeing reference contributors, "
                "or incomparable quote/clock basis. Off-market cannot be established."
            ]
            if not valid
            else [
                f"Delivered mid differs by {delta:+.1f} pips; quote bands are "
                f"{outside:.1f} pips apart (1.0 pip demo tolerance).",
                f"{len(used)}/{len(references)} distinct reference contributors agree; "
                f"delivered quote age is {age:.0f} ms.",
            ]
        )
        return OffMarketState(
            status=status,
            confirmed=self.votes >= 3 if bad else self.recovery >= 5,
            timestamp=now,
            consecutive=self.votes,
            recovery_count=self.recovery,
            reference_bid=ref_bid,
            reference_ask=ref_ask,
            reference_mid=ref_mid,
            delivered_bid=delivered.bid,
            delivered_ask=delivered.ask,
            delivered_mid=mid,
            source_mid=source_mid,
            delivered_age_ms=age,
            mid_delta_pips=delta,
            outside_band_pips=outside,
            source_delta_pips=source_delta,
            reference_quotes=references,
            contributors_used=[q.contributor for q in used] if valid else [],
            excluded=excluded,
            reference_dispersion_pips=(
                max((q.bid + q.ask) / 2 for q in used) - min((q.bid + q.ask) / 2 for q in used)
            )
            * 10000
            if valid
            else None,
            classification=classification,
            reasons=reasons,
        )


class QuoteSimulation:
    """Separate reference, source and delivered views, joined by instrument/basis/time."""

    def __init__(self) -> None:
        self.detector = OffMarketDetector()
        self.frozen_mid: float | None = None
        self.market_shift = 0.0
        self.stepped = False

    def observe(self, scenario: str, offset: int, now: datetime, fair_mid: float) -> OffMarketState:
        from datetime import timedelta

        moved = (
            scenario
            in {
                "offmarket_stale",
                "offmarket_network",
                "offmarket_ack",
                "offmarket_blind",
                "market_reprice",
            }
            and offset >= 2
        )
        if moved and not self.stepped:
            self.market_shift += 0.0018
            self.stepped = True
        reference_mid = fair_mid + self.market_shift
        if (
            scenario
            not in {"offmarket_stale", "offmarket_network", "offmarket_ack", "offmarket_blind"}
            or offset < 2
        ):
            self.frozen_mid = reference_mid
        source_mid = reference_mid + (
            0.0006 if scenario == "offmarket_source" and offset >= 2 else 0
        )
        stale = (
            scenario in {"offmarket_stale", "offmarket_network", "offmarket_ack", "offmarket_blind"}
            and offset >= 2
        )
        delivered_mid = (self.frozen_mid or fair_mid) if stale else source_mid
        age = (offset - 1) * 1000 + 80 if stale else 80

        def quote(name: str, mid: float, age_ms: float) -> ReferenceQuote:
            return ReferenceQuote(
                contributor=name,
                timestamp=now - timedelta(milliseconds=age_ms),
                received_at=now - timedelta(milliseconds=5),
                bid=round(mid - 0.00004, 7),
                ask=round(mid + 0.00004, 7),
            )

        references = [
            quote(
                f"REF-{i + 1}",
                reference_mid + noise,
                2000 if scenario == "reference_loss" and i > 0 else 50 + i * 20,
            )
            for i, noise in enumerate((-0.000005, 0.0, 0.000005))
        ]
        if scenario == "reference_outlier":
            references[-1] = quote("REF-3", reference_mid + 0.002, 90)
        return self.detector.observe(
            now,
            references,
            quote("NYC-DELIVERED", delivered_mid, age),
            quote("TOKYO-SOURCE", source_mid, 45),
        )
