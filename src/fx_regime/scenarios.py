from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from .agent import GroqAgent
from .aiops import AIOPS_SCENARIOS, ConfidenceMonitor
from .detector import RegimeDetector
from .jev import JevClient
from .models import (
    DashboardState,
    FeatureValues,
    Incident,
    InfraStats,
    PricePoint,
    Regime,
    RegimeChange,
    ServiceHealth,
    ServiceObservation,
    TimelineEvent,
)
from .offmarket import OFFMARKET_SCENARIOS
from .operations import RUNBOOKS, ServiceMonitor
from .solace import SolaceBus
from .store import IncidentStore

StateListener = Callable[[DashboardState], Awaitable[None]]
SCENARIOS = AIOPS_SCENARIOS | {
    "volatile",
    "spread",
    "market",
    "infrastructure",
    "feed_loss",
    "telemetry_loss",
    "capacity",
}


class ScenarioEngine:
    """Synthetic one-second producer and independent, journaled explanation worker."""

    def __init__(
        self,
        detector: RegimeDetector,
        jev: JevClient,
        agent: GroqAgent,
        bus: SolaceBus,
        *,
        tick_seconds: float = 1.0,
        store: IncidentStore | None = None,
        investigation_timeout: float = 8.0,
    ) -> None:
        self.detector, self.jev, self.agent, self.bus = detector, jev, agent, bus
        self.tick_seconds = tick_seconds
        self.store = store or IncidentStore()
        self.investigation_timeout = investigation_timeout
        self.monitor = ServiceMonitor()
        self.confidence = ConfidenceMonitor()
        self._aiops_triggered = False
        self._topology_aiops = True
        self.state = DashboardState(
            incidents=self.store.incidents(), llm_enabled=bool(agent.api_key)
        )
        self._listeners: set[StateListener] = set()
        self._task: asyncio.Task[None] | None = None
        self._live_task: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._clock = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
        self._price = 1.11882
        self._rng = random.Random(101)
        self._prewarm_baseline()

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def _normal_values(self) -> FeatureValues:
        return FeatureValues(
            realized_volatility=self._rng.uniform(0.000015, 0.000021),
            spread_pips=self._rng.choice((0.6, 0.7, 0.8, 0.9)),
            quote_rate=self._rng.randint(15, 22),
            solace_latency_ms=self._rng.uniform(6, 8),
            consumer_lag=0,
        )

    def _prewarm_baseline(self) -> None:
        self.detector.reset()
        for offset in range(300):
            values = self._normal_values()
            self.detector.update(
                symbol="EURUSD",
                timestamp=self._clock - timedelta(seconds=299 - offset),
                bid=self._price - values.spread_pips / 20000,
                ask=self._price + values.spread_pips / 20000,
                values=values,
            )

    async def start_live(self) -> None:
        self._ensure_worker()
        if not self._live_task or self._live_task.done():
            self._live_task = asyncio.create_task(self._live_walk())

    async def stop_live(self) -> None:
        for task in (self._live_task, self._task, self._worker):
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _live_walk(self) -> None:
        while True:
            if not self.state.running:
                await self._sample("baseline", 0)
            await asyncio.sleep(1)

    async def start(self, scenario: str) -> DashboardState:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario")
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        topology_aiops = scenario in AIOPS_SCENARIOS
        if topology_aiops != self._topology_aiops:
            self.monitor = ServiceMonitor()
        self._topology_aiops = topology_aiops
        if scenario in AIOPS_SCENARIOS:
            self.confidence = ConfidenceMonitor()
            self._aiops_triggered = False
            for item in self.store.incidents():
                if item.runbook == "aiops" and item.status in {"OPEN", "ACKNOWLEDGED"}:
                    item.status = "RESOLVED"
                    item.updated_at = datetime.now(UTC)
                    item.audit.append(
                        f"{item.updated_at.isoformat()} Demo scenario replaced; "
                        "prior synthetic episode closed, not a measured recovery."
                    )
                    self.store.save(item)
        # Keep incidents and service confirmation across legacy scenario switches.
        self._prewarm_baseline()
        self.state.scenario = scenario  # type: ignore[assignment]
        self.state.running = True
        self.state.last_change = None
        self.state.assessment = None
        self.state.evaluation = []
        self.state.workflow_stage = "monitoring"
        self.state.explanation_latency_ms = None
        self._task = asyncio.create_task(self._run(scenario))
        await self._notify()
        return self.state

    async def reset(self) -> DashboardState:
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self.state.scenario = "baseline"
        self.state.running = False
        await self._notify()
        return self.state

    async def _run(self, scenario: str) -> None:
        try:
            for offset in range(24 if scenario in AIOPS_SCENARIOS else 12):
                await asyncio.sleep(self.tick_seconds)
                await self._sample(scenario, offset)
        finally:
            self.state.running = False
            await self._notify()

    async def _sample(self, scenario: str, offset: int) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        timestamp = max(now, self._clock + timedelta(seconds=1))
        self._clock = timestamp
        values = self._normal_values()
        market = scenario in {
            "volatile",
            "spread",
            "market",
            "capacity",
            "tokyo_burst",
            "market_only",
            "offmarket_stale",
            "market_reprice",
        }
        infrastructure = scenario in {"infrastructure", "capacity"}
        if scenario in {"volatile", "market", "capacity", "tokyo_burst", "market_only"}:
            values.realized_volatility = 0.00022
        if scenario in {"spread", "market", "capacity", "tokyo_burst", "market_only"}:
            values.spread_pips = 5.5
        if scenario in {"market", "capacity", "tokyo_burst", "market_only"}:
            values.quote_rate = 180 if scenario in {"tokyo_burst", "market_only"} else 80
        if scenario in OFFMARKET_SCENARIOS:
            values.spread_pips = 0.8
            if scenario in {"offmarket_stale", "market_reprice"} and offset >= 2:
                values.realized_volatility, values.quote_rate = 0.00022, 180
        if infrastructure:
            values.solace_latency_ms, values.consumer_lag = 155, 130
        self._price = round(
            self._price + self._rng.choice((-1, 1)) * (0.00018 if market else 0.00001), 5
        )
        self.state.aiops = self.confidence.observe(scenario, offset, timestamp, values, self._price)
        observations = []
        for region, suffix in (("LONDON", "LON"), ("NEW_YORK", "NYC")):
            local_issue = region == "LONDON"
            observation = ServiceObservation(
                service_id=f"FX-PRICE-{suffix}-01",
                region=region,
                owner="Pricing application support (demo)",
                timestamp=timestamp,
                ingress_rate=values.quote_rate,
                egress_rate=values.quote_rate,
                p99_latency_ms=8,
            )
            if infrastructure and local_issue:
                observation.p99_latency_ms = 155
                observation.egress_rate = 6
                observation.discard_delta = 3
                observation.sequence_gap_delta = 3
                observation.recent_change = (
                    "Synthetic pricing-consumer release 2 "
                    "minutes before onset; causality unverified."
                )
            if scenario == "feed_loss" and local_issue:
                observation.connected = False
                observation.quote_age_ms = (offset + 1) * 1000
                observation.ingress_rate = observation.egress_rate = 0
            if scenario == "telemetry_loss" and local_issue:
                observation.timestamp -= timedelta(seconds=offset + 4)
            observations.append(observation)
        if self._topology_aiops:
            a = self.state.aiops
            source = {s.evidence_id: s.metrics for s in a.sources}
            observations = [
                ServiceObservation(
                    service_id="FX-SOURCE-TYO-01",
                    region="TOKYO",
                    owner="Market data support (demo)",
                    timestamp=timestamp,
                    ingress_rate=float(source["market"]["quote_rate"]),
                    egress_rate=float(source["market"]["quote_rate"]),
                    quote_age_ms=45,
                ),
                ServiceObservation(
                    service_id="FX-PRICE-NYC-01",
                    region="NEW_YORK",
                    owner="FX platform support (demo)",
                    timestamp=a.sources[1].timestamp,
                    delivery_mode="GUARANTEED",
                    ingress_rate=float(source["semp_queue"]["ingress_rate"]),
                    egress_rate=float(source["semp_queue"]["egress_rate"]),
                    quote_age_ms=float(source["data_quality"]["quote_age_ms"]),
                    backlog=int(source["semp_queue"]["queue_depth"]),
                    oldest_message_ms=float(source["semp_queue"]["oldest_message_ms"]),
                    p99_latency_ms=float(source["corvil_tcp"]["rtt_ms"]),
                ),
            ]
        services = self.monitor.update(timestamp, observations)
        regions = {
            item.observation.region: InfraStats(
                region=item.observation.region,
                timestamp=item.observation.timestamp,
                latency_ms=item.observation.p99_latency_ms,
                consumer_lag=130 if infrastructure and item.observation.region == "LONDON" else 0,
            )
            for item in services
            if item.status != "UNKNOWN"
        }
        comparison = self.state.aiops.offmarket if self._topology_aiops else None
        snapshot, change = self.detector.update(
            symbol="EURUSD",
            timestamp=timestamp,
            bid=comparison.delivered_bid
            if comparison
            else self._price - values.spread_pips / 20000,
            ask=comparison.delivered_ask
            if comparison
            else self._price + values.spread_pips / 20000,
            values=values,
            regions=regions,
        )
        self.state.snapshot, self.state.services = snapshot, services
        self.state.price_history.append(
            PricePoint(timestamp=timestamp, mid=snapshot.mid, bid=snapshot.bid, ask=snapshot.ask)
        )
        self.state.price_history = self.state.price_history[-301:]
        self.state.observations += 1
        self.state.market_condition = "STRESSED" if snapshot.detection.market >= 3 else "NORMAL"
        self.state.service_condition = next(
            (
                status
                for status in ("UNAVAILABLE", "DEGRADED", "UNKNOWN")
                if any(item.status == status for item in services)
            ),
            "HEALTHY",
        )
        if self._topology_aiops:
            if (
                self.state.aiops
                and not self.state.aiops.offmarket
                and self.state.aiops.status in {"AT_RISK", "IMPAIRED"}
            ):
                self.state.service_condition = "DEGRADED"
            elif (
                self.state.aiops
                and not self.state.aiops.offmarket
                and self.state.aiops.status == "UNKNOWN"
            ):
                self.state.service_condition = "UNKNOWN"
            await self._aiops_event(timestamp, values, services)
            self.bus.publish("fx/market/EURUSD/stats", snapshot)
            await self._notify()
            return
        active = {
            item.service_id: item
            for item in self.store.incidents()
            if item.status in {"OPEN", "ACKNOWLEDGED"}
        }
        for health in services:
            observation = health.observation
            incident = active.get(observation.service_id)
            if health.confirmed and health.status == "HEALTHY" and incident:
                incident.status = "RECOVERED"
                incident.recovered_at = incident.updated_at = timestamp
                incident.audit.append(
                    f"{timestamp.isoformat()} Five consecutive healthy observations; recovered."
                )
                self.store.save(incident)
            elif health.confirmed and health.status != "HEALTHY" and not incident:
                evidence = RegimeChange(
                    event="FX_SERVICE_INCIDENT",
                    symbol="EURUSD",
                    timestamp=timestamp,
                    previous_regime=snapshot.regime,
                    new_regime=snapshot.regime,
                    drivers=snapshot.zscores,
                    combined_score=snapshot.combined_score,
                    detection=snapshot.detection,
                    before=self.detector._baseline_values(),
                    after=values,
                    regions=regions,
                    services=services,
                )
                incident = Incident(
                    correlation_id=evidence.correlation_id,
                    service_id=observation.service_id,
                    region=observation.region,
                    owner=str(RUNBOOKS[health.runbook]["owner"]),
                    severity="P3" if health.status == "UNKNOWN" else "P2",
                    opened_at=timestamp,
                    updated_at=timestamp,
                    title=f"{observation.service_id}: {health.status.lower()}",
                    impact=(
                        "Monitoring visibility unavailable; price delivery impact unknown."
                        if health.status == "UNKNOWN"
                        else (
                            "EURUSD pricing-consumer path impaired. Client or "
                            "execution impact is not measured."
                        )
                    ),
                    runbook=health.runbook,
                    evidence=health.findings,
                    audit=[
                        (
                            f"{timestamp.isoformat()} Opened after three consecutive "
                            f"abnormal observations."
                        )
                    ],
                )
                self._enqueue(evidence, incident)
        # Service incidents already carry market evidence. Avoid a second explanation
        # for the same affected path; pure market stress remains an advisory.
        if (
            change
            and change.new_regime == Regime.STRESSED
            and all(h.status == "HEALTHY" for h in services)
        ):
            change.services = services
            self._enqueue(change)
        self.bus.publish("fx/market/EURUSD/stats", snapshot)
        await self._notify()

    async def _aiops_event(
        self, timestamp: datetime, values: FeatureValues, services: list[ServiceHealth]
    ) -> None:
        a = self.state.aiops
        snapshot = self.state.snapshot
        assert a is not None and snapshot is not None
        if (
            a.confirmed
            and a.status in {"AT_RISK", "IMPAIRED", "UNKNOWN"}
            and not self._aiops_triggered
        ):
            self._aiops_triggered = True
            event = RegimeChange(
                event="FX_DATA_CONFIDENCE_CHANGE",
                symbol="EURUSD",
                timestamp=timestamp,
                previous_regime=Regime.NORMAL,
                new_regime=Regime.STRESSED,
                drivers=snapshot.zscores,
                combined_score=a.technical_score,
                before=self.detector._baseline_values(),
                after=values,
                regions={},
                services=services,
                aiops=a.model_copy(deep=True),
            )
            incident = Incident(
                correlation_id=event.correlation_id,
                service_id="FX-PRICE-NYC-01",
                region="NEW_YORK",
                owner="FX platform support · Greg (demo)",
                severity="P3" if a.status == "UNKNOWN" else "P2",
                opened_at=timestamp,
                updated_at=timestamp,
                title=(
                    f"EUR/USD: {a.offmarket.status.replace('_', ' ').lower()}"
                    if a.offmarket
                    else f"EUR/USD data confidence: {a.status.replace('_', ' ').lower()}"
                ),
                impact=(
                    "TYO-NYC-FX-01 · NYC delivered quote compared with independent reference. "
                    "client trading impact is not measured."
                ),
                runbook="aiops",
                evidence=a.reasons,
                audit=[
                    f"{timestamp.isoformat()} Confidence transition confirmed by "
                    "three consecutive abnormal observations."
                ],
            )
            self._enqueue(event, incident)
        if a.status == "WITHIN_LIMITS" and a.confirmed:
            for incident in self.store.incidents():
                if incident.runbook == "aiops" and incident.status in {"OPEN", "ACKNOWLEDGED"}:
                    incident.status = "RECOVERED"
                    incident.recovered_at = incident.updated_at = timestamp
                    incident.audit.append(
                        f"{timestamp.isoformat()} Five healthy source observations; "
                        "data confidence recovered."
                    )
                    self.store.save(incident)

    def _enqueue(self, change: RegimeChange, incident: Incident | None = None) -> None:
        if not self.store.enqueue(change, incident):
            return
        self.state.last_change = change
        self.state.workflow_stage = "triggered"
        self._timeline(
            "signal",
            "FX off-market discrepancy confirmed"
            if change.aiops
            and change.aiops.offmarket
            and change.aiops.offmarket.status == "OFF_MARKET"
            else "FX data confidence transition confirmed"
            if change.aiops
            else "Service incident confirmed"
            if incident
            else "Market advisory confirmed",
        )
        # Optional Direct mirror; the durable local journal owns demo work delivery.
        self.bus.publish(
            "fx/confidence/EURUSD/change"
            if change.aiops
            else "fx/operations/incident"
            if incident
            else "fx/regime/EURUSD/change",
            change,
        )
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    async def drain(self) -> None:
        self._ensure_worker()
        if self._worker:
            await self._worker

    async def _work(self) -> None:
        while item := self.store.claim():
            change, incident_id = item
            started = time.monotonic()

            def current(correlation_id: str = change.correlation_id) -> bool:
                return bool(
                    self.state.last_change
                    and self.state.last_change.correlation_id == correlation_id
                )

            try:
                decisions = self.jev._fallback(change)
                async with asyncio.timeout(self.investigation_timeout):
                    if not change.aiops:
                        decisions = await self.jev.classify(change)
                    if current():
                        self.state.evaluation = decisions
                        self.state.workflow_stage = "agent_running"
                        self._timeline(
                            "evidence",
                            "Corvil, SEMP v1 and market evidence frozen; investigation started"
                            if change.aiops
                            else "Frozen service evidence classified; explanation started",
                        )
                        await self._notify()
                    assessment = await self.agent.explain(change, decisions)
            except TimeoutError:
                assessment = self.agent._fallback(change, decisions, "deadline-fallback")
                assessment.limitations.append(
                    "Provider deadline exceeded; deterministic explanation used."
                )
            except Exception:
                self.store.fail(change.correlation_id)
                self._timeline("error", "Explanation failed; numeric evidence retained")
                await self._notify()
                await asyncio.sleep(0)
                continue
            assessment.latency_ms = int((time.monotonic() - started) * 1000)
            self.store.complete(change.correlation_id, assessment)
            if current():
                self.state.assessment = assessment
                self.state.workflow_stage = "complete"
                self.state.explanation_latency_ms = assessment.latency_ms
                self._timeline("result", "Evidence summary ready; operator checks suggested")
            self.state.completed_investigations += 1
            self.bus.publish(
                "agent/fx-aiops/result" if change.aiops else "agent/fx-regime/result", assessment
            )
            await self._notify()

    async def incident_action(self, incident_id: str, action: str) -> Incident:
        incident = next((i for i in self.store.incidents() if i.incident_id == incident_id), None)
        if not incident:
            raise KeyError(incident_id)
        if action == "acknowledge" and incident.status == "OPEN":
            incident.status = "ACKNOWLEDGED"
        elif action == "resolve" and incident.status == "RECOVERED":
            incident.status = "RESOLVED"
        else:
            raise ValueError("Acknowledge an open incident, or resolve after confirmed recovery.")
        incident.updated_at = datetime.now(UTC)
        incident.audit.append(f"{incident.updated_at.isoformat()} Demo operator: {action}.")
        self.store.save(incident)
        await self._notify()
        return incident

    def _timeline(self, kind: str, label: str) -> None:
        self.state.timeline.append(
            TimelineEvent(timestamp=datetime.now(UTC), kind=kind, label=label)
        )
        self.state.timeline = self.state.timeline[-12:]

    async def _notify(self) -> None:
        self.state.incidents = self.store.incidents()
        self.state.pending_investigations = self.store.pending()
        self.state.failed_investigations = self.store.failed()
        self.state.broker_connected = self.bus.connected
        self.state.provider_calls = {"jev": self.jev.calls, "groq": self.agent.calls}
        for listener in tuple(self._listeners):
            await listener(self.state)
