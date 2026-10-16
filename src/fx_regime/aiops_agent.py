"""Bounded LLM tool investigation over frozen, explicitly simulated source adapters."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

from groq import APIError, AsyncGroq
from pydantic import Field

from .aiops import explanation_graph, source_checks
from .models import AgentAssessment, Cause, JevDecision, PathDiagnosis, RegimeChange, StrictModel


class InvestigationResult(StrictModel):
    assessment: str = Field(min_length=1, max_length=900)
    suspected_component: Literal[
        "nyc_tcp",
        "nyc_queue",
        "tokyo_source",
        "reference",
        "nyc_consumer",
        "nyc_network",
        "nyc_application",
        "unknown",
    ]
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    suggested_next_investigation: str = Field(min_length=1, max_length=700)
    hypothesis_edges: list[
        Literal["market_tcp", "tcp_queue", "queue_data", "tcp_data", "source_data"]
    ] = Field(max_length=4)


def prepared_assessment(
    change: RegimeChange, decisions: list[JevDecision], model: str
) -> AgentAssessment:
    state = change.aiops
    assert state is not None
    if state.offmarket:
        return prepared_offmarket(change, decisions, model)
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
                "Market, Corvil and broker CLI readings are simulated; no real Corvil "
                "or broker CLI collector is connected."
            ),
            "Graph arrows are hypotheses based on the frozen evidence, not established causality.",
        ],
    )


def prepared_offmarket(
    change: RegimeChange, decisions: list[JevDecision], model: str
) -> AgentAssessment:
    state = change.aiops
    assert state is not None and state.offmarket is not None
    check = state.offmarket
    diagnosis = state.diagnosis
    if diagnosis is None:
        diagnosis = PathDiagnosis(
            hypothesis="UNDETERMINED",
            suspected_component="unknown",
            evidence=[],
            next_check="Collect fresh broker CLI and Corvil evidence for this legacy event.",
            limitations=[
                "This historical evidence package predates broker CLI diagnostic captures."
            ],
        )
    component = diagnosis.suspected_component
    first = (
        "Greg, the reference quorum is unavailable, so we cannot establish "
        "whether NYC is off-market."
        if check.status == "UNKNOWN"
        else f"Greg, the NYC delivered quote is {check.mid_delta_pips:+.1f} pips from the "
        f"reference mid and {check.outside_band_pips:.1f} pips outside its bid/ask band."
    )
    explanation = {
        "CONSUMER_BACKPRESSURE": "Corvil shows zero-window evidence on an otherwise healthy "
        "network, while CLI shows a closed transmit window. The consumer may not be reading.",
        "NETWORK_DEGRADATION": "Corvil and broker TCP retransmit evidence agree while the "
        "receive window is open. The NYC network segment may be delaying delivery.",
        "ACK_STALL": "TCP remains healthy, but flow 42 is at its delivered-unacked limit. "
        "Consumer acknowledgement or processing progress may be stalled.",
        "SOURCE_DIVERGENCE": "The fresh Tokyo quote already differs from the reference, NYC "
        "follows it and the transport/flow evidence is normal. Inspect source pricing inputs.",
        "REFERENCE_UNAVAILABLE": "A price verdict requires a fresh independent reference quorum.",
    }.get(
        diagnosis.hypothesis,
        "The quote discrepancy is measured, but missing or conflicting "
        "technical evidence prevents localizing its cause.",
    )
    next_check = diagnosis.next_check
    return AgentAssessment(
        correlation_id=change.correlation_id,
        symbol=change.symbol,
        assessment=first + " " + explanation,
        likely_cause=Cause.INFRASTRUCTURE if component.startswith("nyc_") else Cause.UNCLEAR,
        evidence=check.reasons + [s.summary for s in state.sources if s.source != "MARKET"],
        evidence_refs=[s.evidence_id for s in state.sources],
        suspected_component=component,
        confidence_at_event=state.status,
        offmarket_at_event=check.model_copy(deep=True),
        diagnosis_at_event=diagnosis.model_copy(deep=True),
        checks=source_checks(state),
        graph=explanation_graph(state, ["tcp_queue", "queue_data", "source_data"]),
        suggested_next_investigation=next_check,
        model=model,
        jev_decisions=decisions,
        degraded=model != "deterministic-fallback",
        limitations=diagnosis.limitations
        + [
            "All prices, reference contributors, Corvil and broker CLI readings are simulated.",
            "Off-market means outside a like-for-like indicative reference band, not proven "
            "fair value, an executable arbitrage or a trading recommendation.",
            "1.0 pip tolerance, 500 ms reference age, 100 ms alignment, 20 ms clock uncertainty, "
            "0.5 pip contributor agreement, three confirmations and five "
            "recovery samples are demo policy.",
            "Reference independence is assumed in this simulation. Production requires validation.",
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
                    "Read the frozen simulated Market, Corvil and broker CLI observations,"
                    " including the NYC TCP session, Guaranteed queue, consumer "
                    "freshness, independent reference quotes, comparison verdict and "
                    "unaffected peer."
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
                "All prices and telemetry are synthetic. When offmarket is supplied, "
                "the deterministic "
                "comparator owns its verdict and numbers. First state whether the delivered price "
                "is OFF_MARKET, SUSPECTED or UNKNOWN relative to the indicative reference band. "
                "The dashboard renders exact price and pip figures from the detector separately. "
                "For offmarket packages, never put pip quantities or the word pips in assessment. "
                "Focus that text on the suspected explanation; use may/could for causal claims. "
                "Do not equate a market move or infrastructure anomaly with an off-market quote. "
                "Compare reference vs Tokyo source vs NYC delivered, on the same quote basis. "
                "A fresh source divergence with healthy infrastructure suggests a source/pricing "
                "issue, not TCP. An aligned source plus stale divergent delivery can implicate "
                "the NYC path. An unavailable quorum means withhold the off-market verdict and "
                "inspect reference quality; never claim the price is wrong. "
                "Diagnose performance and data freshness. "
                "A market burst alone does not imply bad data. Distinguish TCP send bytes "
                "from Guaranteed queue messages. A closed transmit window and sustained "
                "broker blocking suggest receiver backpressure. Retransmissions do not "
                "prove payload loss. Compare the unaffected peer. Name a suspected "
                "component, not a proven cause. Temporal order does not prove causality. "
                "Stale evidence means unknown. Never invent ports, metrics or evidence. "
                "Use the diagnosis hypothesis and three-source findings supplied "
                "by the scoped tool. "
                "Distinguish CONSUMER_BACKPRESSURE (normal RTT, zero peer receive window), "
                "NETWORK_DEGRADATION (retransmissions, open window), and ACK_STALL (healthy TCP, "
                "delivered-unacked limit reached). TCP ACKs are not application settlement. "
                "Blocked percentage is about the last minute, not an instantaneous sample. "
                "Corvil and CLI TCP counters may be the same fault, never "
                "independent confidence votes. "
                "Only identity-matched, fresh captures on the AD-active broker "
                "support attribution. "
                "Missing CLI evidence never removes a confirmed price discrepancy, "
                "but its cause stays unknown. "
                "Captures are SIMULATED normalized fields, not a real SSH execution. "
                "Commands are fixed read-only show commands; never invent or "
                "execute arbitrary CLI. "
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
                    "(nyc_tcp, nyc_queue, nyc_consumer, nyc_network, nyc_application, "
                    "tokyo_source, reference, unknown), "
                    "evidence_ids (from tool), "
                    "suggested_next_investigation, hypothesis_edges (subset of market_tcp, "
                    "tcp_queue, queue_data, tcp_data, source_data). If reference quorum "
                    "is unavailable, "
                    "use reference or unknown and no causal edges. If technical "
                    "telemetry is stale, "
                    "use unknown and no edges. For off-market cases include reference and "
                    "data_quality evidence_ids. Use source_data only for SOURCE_DIVERGENCE. "
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
        if state.offmarket:
            if re.search(r"\bpips?\b", result.assessment, flags=re.IGNORECASE):
                raise ValueError("Price-gap quantities belong to deterministic comparison fields")
            expected = state.diagnosis.suspected_component if state.diagnosis else "unknown"
            allowed = {expected, "unknown"}
            if result.suspected_component not in allowed:
                raise ValueError("Suspect contradicts frozen quote comparison")
            if not {"reference", "data_quality"} <= set(result.evidence_ids):
                raise ValueError("Off-market brief must cite the price comparison")
            if state.offmarket.status == "UNKNOWN" and result.hypothesis_edges:
                raise ValueError("Reference failure cannot establish a causal price chain")
        if (
            not state.offmarket
            and state.status == "UNKNOWN"
            and (result.suspected_component != "unknown" or result.hypothesis_edges)
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
