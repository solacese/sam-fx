from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Regime(StrEnum):
    NORMAL = "NORMAL"
    VOLATILE = "VOLATILE"
    STRESSED = "STRESSED"


class Cause(StrEnum):
    MARKET = "MARKET"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    BOTH = "BOTH"
    UNCLEAR = "UNCLEAR"


class MarketTick(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    symbol: str = "EURUSD"
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    bid: float = Field(gt=0, allow_inf_nan=False)
    ask: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_quote(self) -> MarketTick:
        if self.ask < self.bid:
            raise ValueError("ask must be >= bid")
        return self


class InfraStats(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    region: str
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float = Field(ge=0)
    consumer_lag: int = Field(ge=0)


class MacroEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    source: str = "ECB"
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    headline: str
    currency: str = "EUR"


class FeatureValues(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    realized_volatility: float = 0.0
    spread_pips: float = 0.0
    quote_rate: float = 0.0
    solace_latency_ms: float = 0.0
    consumer_lag: float = 0.0


class FeatureZScores(StrictModel):
    volatility: float = 0.0
    spread: float = 0.0
    quote_rate: float = 0.0
    solace_latency: float = 0.0
    consumer_lag: float = 0.0


class DetectionScores(StrictModel):
    shock_5s: float = 0.0
    persistence_30s: float = 0.0
    market: float = 0.0
    infrastructure: float = 0.0
    cusum: float = 0.0


class FeatureSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    symbol: str
    timestamp: AwareDatetime
    bid: float
    ask: float
    mid: float
    values: FeatureValues
    zscores: FeatureZScores
    combined_score: float
    detection: DetectionScores = Field(default_factory=DetectionScores)
    regime: Regime
    candidate_regime: Regime
    persistence_seconds: int


class ServiceObservation(StrictModel):
    """Per-path telemetry. All values in this demo are synthetic fixtures."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    service_id: str
    region: str
    owner: str
    timestamp: AwareDatetime
    connected: bool = True
    quote_age_ms: float = Field(default=100, ge=0)
    ingress_rate: float = Field(default=18, ge=0)
    egress_rate: float = Field(default=18, ge=0)
    p99_latency_ms: float = Field(default=8, ge=0)
    backlog: int = Field(default=0, ge=0)
    oldest_message_ms: float = Field(default=0, ge=0)
    discard_delta: int = Field(default=0, ge=0)
    sequence_gap_delta: int = Field(default=0, ge=0)
    delivery_mode: Literal["DIRECT", "GUARANTEED"] = "DIRECT"
    recent_change: str | None = None
    instruments: list[str] = Field(default_factory=lambda: ["EURUSD"])


class ServiceHealth(StrictModel):
    observation: ServiceObservation
    status: Literal["HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"] = "UNKNOWN"
    findings: list[str] = Field(default_factory=list)
    runbook: str = "telemetry"
    confirmed: bool = False
    observed_at: AwareDatetime


class RegimeChange(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event: Literal["FX_REGIME_CHANGE", "FX_SERVICE_INCIDENT"] = "FX_REGIME_CHANGE"
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    timestamp: AwareDatetime
    previous_regime: Regime
    new_regime: Regime
    drivers: FeatureZScores
    combined_score: float
    detection: DetectionScores = Field(default_factory=DetectionScores)
    before: FeatureValues
    after: FeatureValues
    regions: dict[str, InfraStats]
    macro_events: list[MacroEvent] = Field(default_factory=list)
    services: list[ServiceHealth] = Field(default_factory=list)


class JevDecision(StrictModel):
    question: str
    answer: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict)
    source: Literal["jev", "rules"] = "jev"


class AgentAssessment(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    correlation_id: str
    symbol: str
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    assessment: str
    evidence: list[str]
    likely_cause: Cause
    suggested_next_investigation: str
    jev_decisions: list[JevDecision] = Field(default_factory=list)
    degraded: bool = False
    model: str
    latency_ms: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)


class TimelineEvent(StrictModel):
    timestamp: AwareDatetime
    kind: str
    label: str


class Incident(StrictModel):
    incident_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str
    service_id: str
    region: str
    owner: str
    severity: Literal["P2", "P3"] = "P2"
    status: Literal["OPEN", "ACKNOWLEDGED", "RECOVERED", "RESOLVED"] = "OPEN"
    opened_at: AwareDatetime
    updated_at: AwareDatetime
    recovered_at: AwareDatetime | None = None
    title: str
    impact: str
    runbook: str
    assessment: AgentAssessment | None = None
    evidence: list[str] = Field(default_factory=list)
    audit: list[str] = Field(default_factory=list)


class PricePoint(StrictModel):
    timestamp: AwareDatetime
    mid: float
    bid: float
    ask: float


class DashboardState(StrictModel):
    scenario: Literal[
        "baseline",
        "volatile",
        "spread",
        "market",
        "infrastructure",
        "feed_loss",
        "telemetry_loss",
        "capacity",
    ] = "baseline"
    workflow_stage: Literal[
        "monitoring", "triggered", "evidence_ready", "agent_running", "complete"
    ] = "monitoring"
    running: bool = False
    snapshot: FeatureSnapshot | None = None
    price_history: list[PricePoint] = Field(default_factory=list)
    last_change: RegimeChange | None = None
    evaluation: list[JevDecision] = Field(default_factory=list)
    assessment: AgentAssessment | None = None
    timeline: list[TimelineEvent] = Field(default_factory=list)
    provider_calls: dict[str, int] = Field(default_factory=lambda: {"jev": 0, "groq": 0})
    services: list[ServiceHealth] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    market_condition: str = "NORMAL"
    service_condition: str = "UNKNOWN"
    pending_investigations: int = 0
    completed_investigations: int = 0
    failed_investigations: int = 0
    explanation_latency_ms: int | None = None
    observations: int = 0
    mode: str = "SIMULATED / LOCAL INVESTIGATION"
    broker_connected: bool = False
