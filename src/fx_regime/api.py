from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import GroqAgent
from .config import Settings, get_settings
from .detector import RegimeDetector
from .jev import JevClient
from .models import DashboardState
from .operations import RUNBOOKS
from .scenarios import SCENARIOS, ScenarioEngine
from .solace import SolaceBus
from .store import IncidentStore

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
if not WEB.exists():
    WEB = Path("/app/web")


def create_engine(settings: Settings) -> ScenarioEngine:
    detector = RegimeDetector(
        baseline_seconds=settings.detector_baseline_seconds,
        min_baseline_seconds=settings.detector_min_baseline_seconds,
        persistence_seconds=settings.detector_persistence_seconds,
        recovery_seconds=settings.detector_recovery_seconds,
        entry_score=settings.detector_entry_score,
        stressed_score=settings.detector_stressed_score,
        exit_score=settings.detector_exit_score,
    )
    jev = JevClient(
        settings.jev_api_key
        if settings.enable_external_providers and settings.enable_jev_provider
        else "",
        endpoint=settings.jev_endpoint,
        model=settings.jev_model,
        timeout_seconds=settings.jev_timeout_seconds,
    )
    agent = GroqAgent(
        settings.groq_api_key if settings.enable_external_providers else "",
        settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
    )
    bus = SolaceBus(
        settings.solace_host,
        vpn=settings.solace_vpn,
        username=settings.solace_username,
        password=settings.solace_password,
        client_id=settings.solace_client_id,
    )
    return ScenarioEngine(
        detector,
        jev,
        agent,
        bus,
        tick_seconds=settings.scenario_tick_seconds,
        store=IncidentStore(settings.incident_store_path),
        investigation_timeout=settings.investigation_timeout_seconds,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    engine = create_engine(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine.bus.start()
        await engine.start_live()
        yield
        await engine.stop_live()
        engine.bus.stop()

    app = FastAPI(title="FX Regime Agent", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "broker_enabled": engine.bus.enabled,
            "broker_connected": engine.bus.connected,
            "llm_enabled": bool(engine.agent.api_key),
        }

    @app.get("/api/state", response_model=DashboardState)
    async def state() -> DashboardState:
        return engine.state

    @app.post("/api/scenarios/{scenario}", response_model=DashboardState)
    async def start_scenario(scenario: str) -> DashboardState:
        if scenario not in SCENARIOS:
            raise HTTPException(status_code=404, detail="Unknown scenario")
        return await engine.start(scenario)

    @app.post("/api/recover", response_model=DashboardState)
    async def recover() -> DashboardState:
        return await engine.reset()

    @app.post("/api/incidents/{incident_id}/{action}")
    async def incident_action(incident_id: str, action: str) -> object:
        try:
            return await engine.incident_action(incident_id, action)
        except KeyError as error:
            raise HTTPException(404, "Incident not found") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/runbooks")
    async def runbooks() -> object:
        return RUNBOOKS

    @app.get("/api/handover")
    async def handover() -> JSONResponse:
        return JSONResponse(
            engine.store.handover(),
            headers={"Content-Disposition": 'attachment; filename="sam-fx-handover.json"'},
        )

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue: asyncio.Queue[DashboardState] = asyncio.Queue(maxsize=4)

        async def listener(value: DashboardState) -> None:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(value.model_copy(deep=True))

        async def stream() -> AsyncIterator[str]:
            engine.add_listener(listener)
            try:
                yield f"data: {engine.state.model_dump_json()}\n\n"
                while not await request.is_disconnected():
                    try:
                        value = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {value.model_dump_json()}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                engine.remove_listener(listener)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")
    data_directory = ROOT / "data"
    if not data_directory.exists():
        data_directory = Path("/app/data")
    app.mount("/data", StaticFiles(directory=data_directory), name="data")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("fx_regime.api:app", host=settings.host, port=settings.port)
