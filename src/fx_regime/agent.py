from __future__ import annotations

import json
import time
from typing import Any

from groq import APIError, AsyncGroq

from .models import AgentAssessment, Cause, JevDecision, RegimeChange


class GroqAgent:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 8.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.calls = 0

    async def explain(self, change: RegimeChange, decisions: list[JevDecision]) -> AgentAssessment:
        self.calls += 1
        if not self.api_key:
            return self._fallback(change, decisions, "deterministic-fallback")

        started = time.monotonic()
        client = AsyncGroq(api_key=self.api_key, timeout=self.timeout_seconds)
        try:
            completion = await client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are FXRegimeAgent. Explain only the supplied evidence. Never give "
                            "trading advice. Temporal proximity is not causality; describe only a "
                            "plausible catalyst. "
                            "Return concise JSON matching the supplied schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "regime_change": change.model_dump(mode="json"),
                                "jev_decisions": [item.model_dump() for item in decisions],
                            }
                        ),
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "fx_regime_assessment",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "assessment": {"type": "string"},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                                "likely_cause": {
                                    "type": "string",
                                    "enum": [item.value for item in Cause],
                                },
                                "suggested_next_investigation": {"type": "string"},
                            },
                            "required": [
                                "assessment",
                                "evidence",
                                "likely_cause",
                                "suggested_next_investigation",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
            )
            content = completion.choices[0].message.content or "{}"
            payload: dict[str, Any] = json.loads(content)
            typed_cause = next(
                (item.answer for item in decisions if item.question == "EVIDENCE_CLASS"),
                "UNCLEAR",
            )
            # Jev owns this narrow classification; Groq explains it but cannot silently
            # override the typed decision supplied as evidence.
            payload["likely_cause"] = typed_cause
            return AgentAssessment(
                correlation_id=change.correlation_id,
                symbol=change.symbol,
                jev_decisions=decisions,
                model=self.model,
                latency_ms=int((time.monotonic() - started) * 1000),
                **payload,
            )
        except (APIError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._fallback(change, decisions, f"{self.model} fallback")
        finally:
            await client.close()

    @staticmethod
    def _fallback(
        change: RegimeChange, decisions: list[JevDecision], model: str
    ) -> AgentAssessment:
        choice = next((d.answer for d in decisions if d.question == "EVIDENCE_CLASS"), "UNCLEAR")
        cause = Cause(choice) if choice in Cause._value2member_map_ else Cause.UNCLEAR
        z = change.drivers
        evidence = [
            (
                f"Market: volatility {z.volatility:.1f}σ, spread {z.spread:.1f}σ, quote "
                f"rate {z.quote_rate:.1f}σ."
            ),
            f"Infrastructure: latency {z.solace_latency:.1f}σ, consumer lag {z.consumer_lag:.1f}σ.",
        ]
        affected = [s for s in change.services if s.status in {"UNAVAILABLE", "DEGRADED"}]
        unknown = [s for s in change.services if s.status == "UNKNOWN"]
        for service in change.services:
            observation = service.observation
            evidence.append(
                f"{observation.service_id} / {observation.region}: {service.status}; "
                + (" ".join(service.findings) or "Supplied telemetry is within demo limits.")
            )
            if observation.recent_change and service.status != "UNKNOWN":
                evidence.append(observation.recent_change)
        limitations = [
            "Synthetic evidence and demo thresholds; no client impact or root cause established.",
            "Explanation uses the frozen package; no independent tool investigation was performed.",
        ]
        if not change.services:
            limitations.append(
                "Per-service telemetry was not supplied; regional health is not established."
            )
        if unknown:
            limitations.append(
                "Missing telemetry prevents a health conclusion for the affected path."
            )
        if affected:
            paths = ", ".join(s.observation.service_id for s in affected)
            assessment = f"Delivery impairment observed on {paths}. Evidence class: {cause.value}."
            next_step = (
                (
                    "Compare the affected path with its peer; check source session and "
                    "quote freshness. "
                )
                if any(s.status == "UNAVAILABLE" for s in affected)
                else (
                    "Inspect consumer processing, ingress/egress and Direct discard "
                    "counters; correlate recent changes. "
                )
            )
            next_step += (
                "Follow the linked runbook; recovery or failover requires operator judgment."
            )
        elif unknown:
            assessment = "Monitoring visibility is impaired; service availability remains unknown."
            next_step = (
                "Check the telemetry collector and clock, then verify the "
                "service through an independent path."
            )
        elif cause == Cause.MARKET:
            assessment = f"{change.symbol} market stress detected."
            if change.services:
                assessment += " Supplied service checks show no delivery impairment."
            else:
                assessment += " Service health is not established."
            next_step = (
                "Monitor service capacity, freshness and spread normalization; "
                "review any supplied macro context."
            )
        else:
            assessment = f"{change.symbol} has abnormal statistics. Evidence class: {cause.value}."
            next_step = (
                "Obtain fresh per-service telemetry and compare regional "
                "delivery before assigning a cause."
            )
        for macro in change.macro_events:
            evidence.append(
                f"Context only ({macro.source}, {macro.timestamp.isoformat()}): {macro.headline}"
            )
        return AgentAssessment(
            correlation_id=change.correlation_id,
            symbol=change.symbol,
            assessment=assessment,
            evidence=evidence,
            likely_cause=cause,
            suggested_next_investigation=next_step,
            jev_decisions=decisions,
            degraded=model != "deterministic-fallback",
            model=model,
            limitations=limitations,
        )
