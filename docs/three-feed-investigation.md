# Prices, Corvil and broker CLI: off-market investigation proposal

The outcome is **price quality**, not broker uptime. First establish the discrepancy against
comparable references. Use transport and broker/flow evidence to localize it. Neither a
market burst nor a bad network counter is itself proof of an off-market quote.

| Source | Primary question | Evidence | What it cannot prove |
| --- | --- | --- | --- |
| Prices | Are we away from the comparable market reference? | Reference quorum/bid/ask, source vs delivered quotes, timestamps, sequence and quote basis | Why the delivery path or source changed |
| Corvil | Where does timing or transport behavior change? | Matched flow/segment timing, RTT, retransmits, zero-window probes, peer comparison, capture quality | That application processing completed; encrypted application content without a suitable decoder/access |
| Broker CLI | What is the broker or consumer flow waiting on? | Client TCP state/windows, per-client congestion, flow binding, delivered-unacked count/limit, queue growth/rates, role/epoch | Fair value, application CPU/GC, or a completed pricing calculation |

## Diagnostic cases implemented in the demo

| Price evidence | Corvil | CLI | Leading hypothesis / next check |
| --- | --- | --- | --- |
| Source follows reference; NYC stale | RTT/retransmits normal; zero receiver window | TCP transmit window closed; queue builds; unacked headroom remains | Consumer not reading; inspect socket/processing on the NYC host |
| Source follows reference; NYC stale | RTT/retransmits rise; receiver window open; peer normal | Timed retransmits rise; congestion window shrinks; queue builds | NYC network/host-interface path; compare capture points and host/NIC counters |
| Source follows reference; NYC stale | TCP healthy | Flow 42 at 128/128 delivered-unacked; egress stalls | ACK/processing/configuration stall; inspect application settlement and SDK flow policy |
| Fresh source and NYC diverge together | Normal | Normal TCP and flow progress | Source pricing/input/basis discrepancy; inspect upstream data and mapping |
| Reference contributors reprice and NYC follows | Normal | Normal | Legitimate market move; no off-market investigation |
| Two references agree, third is an outlier | Normal | Normal | Exclude one reference; do not manufacture an off-market incident |
| Reference quorum lost | Any | Any | UNKNOWN price verdict; investigate reference quality |
| Valid price discrepancy, CLI missing or session mismatch | Partial evidence | Unavailable, stale or wrong identity | OFF_MARKET remains; cause is UNDETERMINED |

All rows are controlled scenarios, not live network tests. A hypothesis can remain unknown.
Corvil and broker TCP counters often describe the same fault; they are corroboration, not
independent votes that should be multiplied into an invented confidence percentage.

TCP ACK, messaging transport ACK and application acknowledgement/settlement are different.
Healthy TCP says nothing conclusive about a pricing loop finishing. Likewise, a full flow
limit is evidence to investigate acknowledgement or processing; it does not prove a GC pause,
particular release regression or incorrect ACK policy without application evidence.

## Broker CLI command pack

Exact client, VPN and queue scope is selected from configured topology, never free-form model
text. The demo renders each command, timestamp, status and **normalized simulated fields**.
It does not claim the normalized keys reproduce literal output on every broker version.

```text
show version
show message-spool
show client FX-PRICE-NYC-01 message-vpn fx-demo connections wide
show client FX-PRICE-NYC-01 message-vpn fx-demo stats detail
show client FX-PRICE-NYC-01 message-vpn fx-demo stats queues
show client FX-PRICE-NYC-01 message-vpn fx-demo message-spool-stats egress flow 42
show queue NYC-FX-PRICE-Q message-vpn fx-demo detail
show queue NYC-FX-PRICE-Q message-vpn fx-demo stats
show queue NYC-FX-PRICE-Q message-vpn fx-demo rates
show queue NYC-FX-PRICE-Q message-vpn fx-demo messages oldest count 1
show queue NYC-FX-PRICE-Q message-vpn fx-demo flows detail
show message-vpn fx-demo stats detail
```

The [CLI command reference](https://docs.solace.com/Admin-Ref/CLI-Reference/VMR_CLI_Commands.html)
defines the read-only show command families. The [client/TCP reference](https://docs.solace.com/Security/Viewing-Client-Config-Info.htm)
documents connection/window/counter output. The [Guaranteed messaging guide](https://docs.solace.com/Messaging/Guaranteed-Msg/Monitoring-Guaranteed-Messaging.htm)
covers queues, flows, client spooling and AD-active collection. The [queue configuration guide](https://docs.solace.com/Messaging/Guaranteed-Msg/Configuring-Queues.htm)
explains the delivered-unacked limit. Corvil's [official overview](https://www.pico.net/products/corvil-analytics/)
describes packet-derived segment and session analytics.

CLI is the chosen access surface, not proof that it necessarily exposes more than every SEMP
interface. Available fields depend on broker version, platform and permissions. The collector
must probe capabilities and record unsupported fields rather than silently substituting zero.
Do not use experimental window fields as operational evidence.

## Measurement and collection rules

- Use continuous price and Corvil observations for detection. Cache scoped CLI baselines
  every 5–10 seconds, subject to a measured broker management-plane budget. These intervals
  are a proposed operating policy, not a tested safe polling rate for a production bank.
- A price event freezes recent evidence and requests a bounded targeted CLI pack. Return an
  initial explanation from valid cached evidence; enrich it when deeper captures complete.
  Do not serialize a wide CLI sweep into the critical quote path or promise a ten-second SLO.
- Match broker boot/role, VPN, client, local/remote TCP tuple, connection epoch, queue and
  egress flow. Check the AD-active broker for Guaranteed stats. Do not combine counters
  across a reconnect, failover or counter reset. Port reuse alone is not a session match.
- Track capture time separately from metric window. Current gauges, one-second rates,
  cumulative counters, interval deltas and recent-window percentages have different meanings.
  Broker blocked % summarizes recent behavior (about a minute), not an instantaneous gauge.
- Derive retransmit deltas only from valid samples on the same epoch. Missing or negative
  deltas invalidate attribution. Corvil capture drops or poor timing quality weaken the
  packet evidence; the demo withholds a technical diagnosis in those cases.
- `unacked_limit_headroom` is derived as configured per-flow limit minus delivered-unacked.
  It is not the TCP receive window or a measurement of messaging transport-window credit.
  Oldest-message age is simulated enqueue metadata in this demo, not a promised literal CLI
  field on all versions. A production parser must verify metadata availability and clock basis.
- Use read-only identities and fixed commands. No `clear`, resets, queue payload dumps,
  wildcard all-client scans, configuration changes, failover or arbitrary model-generated CLI.
  The optional oldest-message metadata read is limited to one message and does not show payload.

## What runs today, and the next integration step

The AWS worker can invoke the real configured LLM over a frozen synthetic evidence package.
GitHub Pages replays prepared packages. No SSH session, broker CLI poller, real Corvil
collector or production FX reference feed is connected. Existing broker event mirroring is
preserved; actual SAM request/result orchestration remains integration work.

The live integration should be a separate version-aware read-only collector that emits the
normalized `BrokerCliSnapshot` contract with command provenance, raw-output retention policy,
collection status, sampling interval and identity/epoch metadata. Qualify it against the actual
software/appliance version, management permissions and realistic command cost first. Supply
application/runtime evidence only through separately approved tools if the operator wants to
resolve an ACK-stall hypothesis further. The LLM should explain and suggest investigation;
it must neither decide the numeric off-market verdict nor alter the platform.
