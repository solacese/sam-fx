from fastapi.testclient import TestClient

from fx_regime.api import create_app
from fx_regime.config import Settings


def test_health_and_state() -> None:
    app = create_app(
        Settings(_env_file=None, incident_store_path=":memory:", scenario_tick_seconds=0)
    )
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        state = client.get("/api/state")
        assert state.status_code == 200
        assert state.json()["scenario"] == "baseline"


def test_unknown_scenario_rejected() -> None:
    app = create_app(Settings(_env_file=None, incident_store_path=":memory:"))
    with TestClient(app) as client:
        response = client.post("/api/scenarios/unknown")
        assert response.status_code == 404


def test_handover_and_incident_actions():
    app = create_app(
        Settings(
            _env_file=None, incident_store_path=":memory:", scenario_tick_seconds=0, solace_host=""
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/runbooks").json()["feed"]["checks"]
        assert client.post("/api/incidents/missing/acknowledge").status_code == 404
        export = client.get("/api/handover")
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        assert "Synthetic demo" in export.json()["mode"]
        assert client.post("/api/recover").json()["scenario"] == "baseline"
