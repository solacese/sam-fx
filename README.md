# sam-fx

A static FX desk matching the supplied design: reference rates, an EUR/USD candlestick snapshot, and a simple desk chat. Dark mode with classic green accents.

- Three prepared chat answers: current price, last 30 minutes, and feed status.
- Subtle replay animation with pause/play and reduced-motion support.
- 5m candles, with 15m and 1h aggregates; source OHLC rows are expandable in chat.
- Mesh connection summary and deterministic demo rules.
- No LLM, backend, external assets, live market connection or order execution.

## Open

Open `index.html` directly, or run `python3 -m http.server 8080`.

Published at https://solacese.github.io/sam-fx/ using GitHub Pages from `main`, root directory. No build step.

## Data

`data/snapshot.json` records the supplied screenshot's reference rates and last six OHLC rows. Earlier candles approximate the reference chart. These are design fixtures, **not verified live or historical market data**. The animation does not modify prices or imply a live connection.

`data/bundle.js` embeds the same data to allow offline and `file://` use. After editing the JSON, run `python3 scripts/bundle.py`. Dates and prepared responses stay fixed at the supplied snapshot.

The starting `prompt.md` is an earlier, superseded brief. The latest supplied screenshot and request for three answers define this version.

## Verify

`python3 scripts/check_data.py` checks OHLC validity, the three response contract, the quoted 30-minute statistics, and bundle consistency. `node --check app.js` checks syntax. Browser checks cover chat, timeframes, tabs, animation controls and responsive layout.
