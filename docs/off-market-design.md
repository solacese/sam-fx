# Off-market investigator

## The operator question

“Is the price delivered to NYC materially away from the comparable reference, and where
should Greg investigate?” A delivery anomaly is evidence for investigation, not proof of a
bad price. A market-wide move should not be treated as a platform fault.

## Evidence and verdict

The demo creates three distinct reference contributors on separate simulated paths. Reference
independence is an assumption of the simulation, not a property proven by three vendor labels.
The largest mutually agreeing cluster of at least two fresh contributors supplies median bid
and median ask. Duplicate contributor IDs cannot manufacture quorum. Different instrument or
quote basis, stale/future timestamps, excessive clock uncertainty and disagreement exclude
observations. No quorum means UNKNOWN, no midpoint gap and no price verdict.

Comparison is between like-for-like spot indicative quotes, at the current observation time.
The delivered quote may have an older source timestamp: that age is exactly what a stale
consumer case is intended to expose. It is not backdated to disguise its current divergence.
A stale source cannot establish a source-divergence diagnosis. Mids make the discrepancy easy
to see; alerting uses separation of bid/ask bands to account for spreads.

Demo policy: reference age ≤500 ms, contributor times within 100 ms, clock uncertainty ≤20 ms,
mid dispersion ≤0.5 pips, ≥1.0 pip separation beyond the reference quote band, three distinct
consecutive abnormal seconds to confirm, five healthy comparisons to recover. These settings
are deliberately readable at one-second demo speed. Real FX requires tighter instrument-,
venue-, liquidity-, size- and workload-specific policies and independently qualified clocks.
The tolerance is configurable in source only in this v1; it is not empirically calibrated.

The comparator owns OFF_MARKET / SUSPECTED / WITHIN_BAND / UNKNOWN. The model cannot override
this. A frozen event retains bid/ask, contributor observations, reasons and age for audit even
when the live feeds recover. Model suspects are constrained to the evidence: a fresh source
mismatch with normal transport cannot be labelled a TCP fault, while a reference quorum
failure cannot establish any price-propagation causal chain.

## Why and where

- Source aligned, consumer stale and divergent: inspect delivery path. Corvil RTT/retransmits,
  SEMP closed transmit window/blocking, queue depth and peer observations support a hypothesis.
- Fresh source divergent, consumer follows it, transport healthy: inspect source mapping,
  pricing inputs or quote basis. This does not identify an actual misconfiguration by itself.
- Reference unavailable: repair/validate the comparison evidence before assigning a price fault.
- Real market move and all views follow: no investigation.
- Single reference outlier, two agree: exclude the outlier; no off-market alert.

Corvil describes packet-derived, time-synchronized evidence and one-second RTT,
retransmission and congestion metrics in its [official product description](https://www.pico.net/products/corvil-analytics/).
Those fields are simulated here; no collector or packet capture is connected. The existing
SEMP v1 simulation remains based on client TCP and Guaranteed queue observations. See
[Solace's SEMP v1 documentation](https://docs.solace.com/Admin/SEMP/Using-Legacy-SEMP.htm).

Daily central-bank reference rates are unsuitable as an intraday quote comparator: the
[ECB states](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
that its rates are normally updated daily and are for information purposes, with transactional
use strongly discouraged. No ECB value is used by this comparator.

## Production boundaries

This is an illustrative reference-discrepancy monitor, not a fair-value engine, an executable
arbitrage test, a trade recommendation or a price-suppression control. Validate instrument,
value date/tenor, bid/ask orientation, quote size, executable/indicative basis and contributor
independence before comparing production quotes. Obtain independent feeds and permissions,
use approved clock synchronization and packet capture, record reference quality and capture
loss, calibrate tolerance and persistence against labelled incidents, and review false alerts
and missed events across volatile periods. A majority can still be wrong if contributors share
a source; add source lineage and alternate references for a production pilot.

The demo does not automatically switch feeds, restart consumers, change pricing or trade. AWS
uses a local durable investigation worker and real configured LLM calls over synthetic evidence;
GitHub Pages is a prepared browser replay. Actual SAM request/result orchestration, live
Corvil/SEMP collectors and production price feeds remain integration work.
