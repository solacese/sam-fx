Build a focused prototype called **FX Regime Agent** using the existing Solace FX demo as the starting point:

`https://github.com/solacese/fxdemo/tree/master`

The goal is intentionally narrow: detect meaningful FX regime changes in real time from a small set of market and Solace statistics, then trigger **one Agent Mesh agent** to investigate and explain what changed.

Do not build a large multi-agent platform. Keep the first version simple, credible, and easy to demo to an FX infrastructure leader.

## Core idea

Solace carries the real-time FX and infrastructure events.

A lightweight statistical detector runs continuously at **1-second resolution** and watches a small number of signals:

- FX returns / realized volatility
- bid-ask spread
- quote or message rate
- Solace messaging latency
- consumer lag

Use three time horizons:

- **1 second:** update features
- **5 seconds:** detect a sudden shock
- **30 seconds:** confirm persistence
- **5 minutes:** rolling baseline for what is normal now

The regime detector should compare short-term behavior against the 5-minute baseline rather than relying only on hardcoded absolute thresholds.

For example:

```text
EUR/USD

5s volatility vs baseline: +4.1σ
spread vs baseline:        +3.4σ
quote rate:                +5.8σ
Solace latency:            +0.2σ
consumer lag:              normal
```

When the combined anomaly score crosses a threshold and persists for roughly 3–5 seconds, publish a Solace event such as:

```text
fx/regime/EURUSD/change
```

with a payload similar to:

```json
{
  "event": "FX_REGIME_CHANGE",
  "symbol": "EURUSD",
  "previous_regime": "NORMAL",
  "new_regime": "STRESSED",
  "timestamp": "...",
  "drivers": {
    "volatility_zscore": 4.1,
    "spread_zscore": 3.4,
    "quote_rate_zscore": 5.8,
    "solace_latency_zscore": 0.2,
    "consumer_lag": "NORMAL"
  }
}
```

## Regime logic

Start with only a few regime states:

```text
NORMAL
VOLATILE
STRESSED
```

Avoid building a sophisticated ML model initially.

Use simple, explainable logic such as:

- EWMA
- rolling z-scores
- CUSUM
- optional lightweight change-point detection

The detector should include hysteresis so the state does not oscillate every second.

For example:

```text
NORMAL
→ anomaly threshold crossed
→ persists for 3–5 seconds
→ STRESSED
```

Returning to NORMAL should also require sustained normalization.

## Single Agent Mesh agent

When `FX_REGIME_CHANGE` is published, wake a single agent called:

`FXRegimeAgent`

This agent should receive:

- the regime-change event
- before/after market statistics
- before/after Solace statistics
- any relevant market or macro event from roughly the previous 30–60 seconds
- optionally a few previous similar regime changes

The agent's job is to answer three questions:

1. **What changed?**
2. **Is this more likely market-driven, infrastructure-driven, or both?**
3. **What is the concise explanation for the operator?**

The result should be short and operationally useful.

Example:

```text
EUR/USD entered a stressed regime.

Volatility increased 4.1×, spreads widened 2.8× and quote activity increased 6.3× relative to the recent baseline.

Solace messaging latency and consumer lag remain within normal ranges.

An ECB announcement occurred 11 seconds before the change.

Assessment: likely market-driven rather than infrastructure-driven.
```

A second scenario should produce the opposite result:

```text
EUR/USD anomaly detected.

Market volatility increased only modestly, while London delivery latency increased 4.6× and consumer lag appeared only in London.

New York remains normal.

Assessment: likely infrastructure-driven rather than a genuine FX market regime change.
```

## Jev use

We already have Jev credentials.

Use Jev only for **small, typed semantic decisions**.

Do not use Jev for numeric calculations.

Good questions include:

```text
Does this announcement represent a material policy surprise?

YES
NO
UNCLEAR
```

or:

```text
Is this announcement directly relevant to EUR?

DIRECT
INDIRECT
NO
UNCLEAR
```

or:

```text
Based on the supplied evidence, is the event primarily:

MARKET
INFRASTRUCTURE
BOTH
UNCLEAR
```

Jev output should be structured and passed to the FX Regime Agent as evidence.

Example:

```json
{
  "question": "MATERIAL_POLICY_SURPRISE",
  "answer": "YES",
  "confidence": 0.91
}
```

Do not ask Jev broad questions like:

```text
Why did EUR/USD move?
```

or:

```text
What should the trader do?
```

Those are too open-ended.

## Groq use

We already have Groq credentials.

Use Groq for the fast LLM reasoning and explanation layer.

The Groq-powered `FXRegimeAgent` should receive:

- structured regime metrics
- relevant Solace health metrics
- Jev decisions
- recent macro/news context
- optional historical comparison

Its output should be:

```text
Assessment
Evidence
Likely cause
Suggested next investigation
```

Keep the response concise enough to appear live on the dashboard.

Do not continuously send every FX tick to Groq.

The LLM should only be invoked after a meaningful regime-change event.

This is a core architectural principle:

> **statistics run continuously; AI wakes only when something important changes.**

## Correlation

Keep event correlation simple in V1.

Correlate events using:

- FX pair
- timestamp
- region where relevant
- 30–60 second event window

For example:

```text
FX_REGIME_CHANGE EURUSD
at 13:45:02
```

should look for:

```text
macro events between 13:44:02 and 13:45:02
Solace anomalies in the same time window
consumer lag in the same time window
```

The agent should not assume that temporal proximity proves causality.

Instead say:

```text
ECB announcement occurred 11 seconds before the regime change and is a plausible catalyst.
```

rather than:

```text
ECB caused the move.
```

unless the evidence is strong enough.

## Solace topics

Use a clean topic hierarchy.

For example:

```text
fx/market/EURUSD/price
fx/market/EURUSD/stats
fx/regime/EURUSD/change

infra/solace/LONDON/stats
infra/solace/LONDON/health

macro/ECB/event

agent/fx-regime/request
agent/fx-regime/result
```

The agent should subscribe to regime-change requests, not raw market-data ticks.

## Dashboard

Extend the existing FX dashboard rather than replacing it.

Keep the UI simple.

Show:

### 1. Live FX

```text
EUR/USD
1.1782
STRESSED
```

### 2. Current statistics

```text
Volatility   +4.1σ
Spread       +3.4σ
Quote rate   +5.8σ
Latency      +0.2σ
Consumer lag Normal
```

### 3. Agent explanation

```text
Likely market-driven.

ECB announcement detected 11 seconds earlier.
Jev classified it as a material policy surprise: 91%.

Solace infrastructure remains healthy.
```

### 4. Small timeline

```text
13:44:58 ECB event
13:45:00 volatility rises
13:45:02 regime change
13:45:03 Agent Mesh triggered
13:45:05 assessment available
```

## Demo scenarios

Implement exactly two primary scenarios first.

### Scenario A — genuine market regime change

Simulate:

```text
ECB announcement
EUR/USD volatility spike
spread widening
quote rate increase
Solace latency normal
consumer lag normal
```

Expected output:

```text
Likely genuine market-driven regime change.
```

### Scenario B — infrastructure-driven anomaly

Simulate:

```text
EUR/USD relatively stable
London Solace/application latency rises
consumer lag rises
New York remains normal
```

Expected output:

```text
Likely infrastructure-driven rather than a genuine FX regime change.
```

These two contrasting scenarios are enough to make the story clear.

## Important design rules

Do not:

- send all raw market data to the LLM
- build 10+ agents
- make autonomous trading decisions
- claim causality from correlation alone
- use Jev for arithmetic
- use LLMs for millisecond-level detection

Do:

- use statistics for detection
- use Solace to publish meaningful change events
- use Jev for narrow semantic classification
- use Groq for fast reasoning and explanation
- keep the result understandable in under 10 seconds

## Positioning

The product story should be:

> **We do not send the FX firehose to an LLM. We monitor it statistically at one-second resolution. When the data moves into a materially different regime, Solace turns that change into an event and wakes an Agent Mesh agent. Jev makes a few precise semantic decisions and Groq combines the evidence into a concise explanation of what changed and whether it looks market-driven or infrastructure-driven.**

The value is not autonomous FX trading.

The value is:

> **real-time detection plus intelligent interpretation of meaningful change.**

The first prototype should feel like a small, natural intelligence layer on top of an existing Solace FX deployment, not a redesign of the bank's FX business.