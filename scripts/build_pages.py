"""Build an offline Pages demo using the same Python detector and prepared answers."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fx_regime.agent import GroqAgent
from fx_regime.detector import RegimeDetector
from fx_regime.jev import JevClient
from fx_regime.operations import RUNBOOKS
from fx_regime.scenarios import ScenarioEngine
from fx_regime.solace import SolaceBus

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "pages"


async def clip(scenario: str) -> list[dict[str, object]]:
    engine = ScenarioEngine(
        RegimeDetector(), JevClient(""), GroqAgent("", "prepared"), SolaceBus(""), tick_seconds=0
    )
    frames = []
    for i in range(30 if scenario == "baseline" else 24):
        active = scenario != "baseline" and i < 12
        engine.state.scenario = scenario if active else "baseline"
        engine.state.running = active
        await engine._sample(scenario if active else "baseline", i)
        await engine.drain()
        frames.append(engine.state.model_dump(mode="json"))
    engine.store.db.close()
    return frames


async def build() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scenarios = ["baseline", "market", "infrastructure", "feed_loss", "telemetry_loss", "capacity"]
    clips = {name: await clip(name) for name in scenarios}
    data = {"version": 1, "runbooks": RUNBOOKS, "clips": clips}
    (OUTPUT / "demo-data.js").write_text(
        "window.SamFxFixtures=" + json.dumps(data, separators=(",", ":")) + ";\n"
    )
    for name in ("app.js", "styles.css", "demo.js"):
        shutil.copy2(ROOT / "web" / name, OUTPUT / name)
    html = (ROOT / "web" / "index.html").read_text()
    html = html.replace('href="/"', 'href="./"').replace("/assets/", "./")
    html = html.replace(
        '<script src="./app.js"',
        '<script src="./demo-data.js" defer></script>'
        '<script src="./demo.js" defer></script><script src="./app.js"',
    )
    html = html.replace('href="/api/handover"', 'href="#handover"')
    html = html.replace("Local incident journal", "Browser incident journal")
    html = html.replace("synthetic market and telemetry", "synthetic replay · no live feed or LLM")
    (OUTPUT / "index.html").write_text(html)
    (OUTPUT / ".nojekyll").touch()
    print(f"Built {OUTPUT} with {sum(map(len, clips.values()))} validated simulation frames")


if __name__ == "__main__":
    asyncio.run(build())
