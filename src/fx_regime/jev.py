from __future__ import annotations

from typing import Any

import httpx

from .models import Cause, JevDecision, RegimeChange


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        model: str = "jev-latest",
        timeout_seconds: float = 4.0,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.calls = 0

    async def classify(self, change: RegimeChange) -> list[JevDecision]:
        self.calls += 1
        if not self.api_key:
            return self._fallback(change)

        body = {
            "model": self.model,
            "state": change.model_dump(mode="json"),
            "questions": {
                "material_policy_surprise": {
                    "type": "choice",
                    "instructions": (
                        "Does a supplied announcement represent a material policy surprise? "
                        "Choose UNCLEAR when no announcement is supplied."
                    ),
                    "criteria": {
                        "YES": "Material surprise",
                        "NO": "Not material",
                        "UNCLEAR": "Insufficient evidence",
                    },
                },
                "eur_relevance": {
                    "type": "choice",
                    "instructions": (
                        "Is a supplied announcement directly relevant to EUR? "
                        "Choose UNCLEAR when no announcement is supplied."
                    ),
                    "criteria": {
                        "DIRECT": "Directly relevant",
                        "INDIRECT": "Indirectly relevant",
                        "NO": "Not relevant",
                        "UNCLEAR": "Insufficient evidence",
                    },
                },
                "evidence_class": {
                    "type": "choice",
                    "instructions": "Based only on the supplied evidence, classify the event.",
                    "criteria": {
                        "MARKET": "Market metrics dominate while infrastructure remains normal",
                        "INFRASTRUCTURE": (
                            "Infrastructure metrics dominate while market remains stable"
                        ),
                        "BOTH": "Both are materially abnormal",
                        "UNCLEAR": "Evidence does not support a clear class",
                    },
                },
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
            return self._parse(response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return self._fallback(change)

    @staticmethod
    def _parse(body: dict[str, Any]) -> list[JevDecision]:
        decisions: list[JevDecision] = []
        choices = {
            "material_policy_surprise": {"YES", "NO", "UNCLEAR"},
            "eur_relevance": {"DIRECT", "INDIRECT", "NO", "UNCLEAR"},
            "evidence_class": {"MARKET", "INFRASTRUCTURE", "BOTH", "UNCLEAR"},
        }
        if "evidence_class" not in body["answers"]:
            raise ValueError("missing evidence class")
        for question, answer in body["answers"].items():
            selected = str(answer.get("choice", "UNCLEAR"))
            if question not in choices or selected not in choices[question]:
                raise ValueError("invalid typed answer")
            decisions.append(
                JevDecision(
                    question=question.upper(),
                    answer=selected,
                    confidence=float(answer.get("confidence", 0.0)),
                    probabilities={
                        str(key): float(value)
                        for key, value in answer.get("probabilities", {}).items()
                    },
                )
            )
        return decisions

    @staticmethod
    def _fallback(change: RegimeChange) -> list[JevDecision]:
        z = change.drivers
        market = max(z.volatility, z.spread, z.quote_rate)
        infrastructure = max(z.solace_latency, z.consumer_lag)
        if any(s.status in {"DEGRADED", "UNAVAILABLE"} for s in change.services):
            infrastructure = max(infrastructure, 3)
        if change.aiops and change.aiops.status in {"AT_RISK", "IMPAIRED"}:
            infrastructure = max(infrastructure, 3)
        missing = any(s.status == "UNKNOWN" for s in change.services) or bool(
            change.aiops and change.aiops.status == "UNKNOWN"
        )
        if missing and infrastructure < 3:
            cause = Cause.UNCLEAR
        elif market >= 3 and infrastructure < 2:
            cause = Cause.MARKET
        elif infrastructure >= 3 and market < 2:
            cause = Cause.INFRASTRUCTURE
        elif market >= 3 and infrastructure >= 3:
            cause = Cause.BOTH
        else:
            cause = Cause.UNCLEAR
        if change.aiops and change.aiops.offmarket:
            cause = (
                Cause.INFRASTRUCTURE
                if change.aiops.offmarket.classification == "STALE_DELIVERY"
                else Cause.UNCLEAR
            )
        return [
            JevDecision(
                question="MATERIAL_POLICY_SURPRISE",
                answer="UNCLEAR",
                confidence=0,
                source="rules",
            ),
            JevDecision(
                question="EUR_RELEVANCE",
                answer="UNCLEAR",
                confidence=0,
                source="rules",
            ),
            JevDecision(
                question="EVIDENCE_CLASS",
                answer=cause.value,
                confidence=0,
                source="rules",
            ),
        ]
