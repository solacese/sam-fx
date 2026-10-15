"""Bounded LLM tool investigation over frozen, explicitly simulated source adapters."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from groq import APIError, AsyncGroq
from pydantic import Field

from .aiops import explanation_graph, source_checks
from .models import AgentAssessment, Cause, JevDecision, RegimeChange, StrictModel


class InvestigationResult(StrictModel):
    assessment: str = Field(min_length=1, max_length=900)
    suspected_component: Literal["nyc_tcp", "nyc_queue", "tokyo_source", "unknown"]
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    suggested_next_investigation: str = Field(min_length=1, max_length=700)
    hypothesis_edges: list[Literal["market_tcp", "tcp_queue", "queue_data", "tcp_data"]] = Field(
        max_length=4
    )


def prepared_assessment(
    change: RegimeChange, decisions: list[JevDecision], model: str
) -> AgentAssessment:
    state = change.aiops
    assert state is not None
    unknown = state.status == "UNKNOWN"
    component = (
        "unknown" if unknown else "nyc_queue" if state.scenario == "queue_pressure" else "nyc_tcp"
    )
    text = (
        (
            "Greg, monitoring evidence is stale. Confidence in the New York "
            "EUR/USD path is unknown; verify the collectors before blaming a "
            "connection."
        )
        if unknown
        else "Greg, EUR/USD delivery confidence fell on the New York consumer path. "
        + (
            "The Guaranteed queue is the leading suspect; TCP peer measurements remain normal."
            if component == "nyc_queue"
            else (
                "The NYC TCP consumer connection is the leading suspect: packet and"
                " broker observations both show delivery pressure."
            )
        )
    )
    refs = [s.evidence_id for s in state.sources]
    return AgentAssessment(
        correlation_id=change.correlation_id,
        symbol=change.symbol,
        assessment=text,
        likely_cause=Cause.UNCLEAR
        if unknown
        else Cause.BOTH
        if state.market_regime == "STRESSED"
        else Cause.INFRASTRUCTURE,
        evidence=[s.summary for s in state.sources],
        evidence_refs=refs,
        suspected_component=component,
        confidence_at_event=state.status,
        checks=source_checks(state),
        graph=explanation_graph(state, ["market_tcp", "tcp_queue", "queue_data", "tcp_data"]),
        suggested_next_investigation="Check the telemetry collectors and an independent peer."
        if unknown
        else (
            "Inspect FX-PRICE-NYC-01, broker 10.30.0.5:55555 → consumer "
            "10.30.1.20:43172; compare socket consumption and NYC-FX-PRICE-Q "
            "with the unaffected peer."
        ),
        model=model,
        jev_decisions=decisions,
        degraded=model != "deterministic-fallback",
        limitations=[
            (
                "Market, Corvil and SEMP v1 readings are simulated; no real Corvil "
                "or SEMP collector is connected."
            ),
            "Graph arrows are hypotheses based on the frozen evidence, not established causality.",
        ],
    )


async def investigate(
    change: RegimeChange, decisions: list[JevDecision], api_key: str, model: str, timeout: float
) -> AgentAssessment:
    if not api_key:
        return prepared_assessment(change, decisions, "deterministic-fallback")
    state = change.aiops
    assert state is not None
    started = time.monotonic()
    client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
    tools: Any = [
        {
            "type": "function",
            "function": {
                "name": "inspect_fx_path",
                "description": (
                    "Read the frozen simulated Market, Corvil and SEMP v1 observations,"
                    " including the NYC TCP session, Guaranteed queue, consumer "
                    "freshness and unaffected peer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"path_id": {"type": "string", "enum": [state.path_id]}},
                    "required": ["path_id"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages: Any = [
        {
            "role": "system",
            "content": (
                "You are the FX AIOps investigator briefing Greg. Call inspect_fx_path first. "
                "All telemetry is synthetic. Diagnose performance and data freshness. "
                "A market burst alone does not imply bad data. Distinguish TCP send bytes "
                "from Guaranteed queue messages. A closed transmit window and sustained "
                "broker blocking suggest receiver backpressure. Retransmissions do not "
                "prove payload loss. Compare the unaffected peer. Name a suspected "
                "component, not a proven cause. Temporal order does not prove causality. "
                "Stale evidence means unknown. Never invent ports, metrics or evidence. "
                "No remediation actions or trading advice."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "path_id": state.path_id,
                    "confidence": state.status,
                    "confirmed_at": state.timestamp.isoformat(),
                    "task": "Investigate quickly and brief Greg.",
                }
            ),
        },
    ]
    try:
        first = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "inspect_fx_path"}},
            temperature=0.1,
            max_completion_tokens=600,
        )
        message = first.choices[0].message
        if not message.tool_calls or len(message.tool_calls) != 1:
            raise ValueError("Expected one scoped investigation call")
        call = message.tool_calls[0]
        args = json.loads(call.function.arguments)
        if call.function.name != "inspect_fx_path" or args != {"path_id": state.path_id}:
            raise ValueError("Tool call outside the incident scope")
        # The approved demo tool reads immutable observations for this correlation ID only.
        messages.append(message.model_dump(exclude_none=True))
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": state.model_dump_json()}
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "Return JSON: assessment (2 short sentences for Greg), suspected_component "
                    "(nyc_tcp, nyc_queue, tokyo_source, unknown), evidence_ids (from tool), "
                    "suggested_next_investigation, hypothesis_edges (subset of market_tcp, "
                    "tcp_queue, queue_data, tcp_data). If stale, use unknown and no edges. "
                    "Use market_tcp only for tokyo_burst; tcp_queue only when TCP and queue "
                    "both deteriorate; queue_data when queue and quote age rise; tcp_data "
                    "for TCP pressure without queue growth. Use likely/suspect language. "
                    "Every causal statement must use may, could or likely. No proven cause."
                ),
            }
        )
        final = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_completion_tokens=1600,
        )
        result = InvestigationResult.model_validate_json(final.choices[0].message.content or "{}")
        known = {s.evidence_id: s for s in state.sources}
        if any(ref not in known for ref in result.evidence_ids):
            raise ValueError("Unknown evidence reference")
        if state.status == "UNKNOWN" and (
            result.suspected_component != "unknown" or result.hypothesis_edges
        ):
            raise ValueError("Missing telemetry cannot establish a suspect connection")
        assessment = prepared_assessment(change, decisions, model)
        assessment.degraded = False
        assessment.assessment = result.assessment
        assessment.suspected_component = result.suspected_component
        assessment.suggested_next_investigation = result.suggested_next_investigation
        assessment.evidence_refs = list(dict.fromkeys(result.evidence_ids))
        assessment.evidence = [known[ref].summary for ref in assessment.evidence_refs]
        assessment.graph = explanation_graph(state, result.hypothesis_edges)
        assessment.latency_ms = int((time.monotonic() - started) * 1000)
        return assessment
    except (APIError, IndexError, KeyError, TypeError, ValueError):
        return prepared_assessment(change, decisions, f"{model} fallback")
    finally:
        await client.close()
