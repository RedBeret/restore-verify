from fastapi.testclient import TestClient
from recoverops_api import main


def test_root_identifies_project() -> None:
    response = TestClient(main.app).get("/")

    assert response.status_code == 200
    assert response.json()["project"] == "restore-verify"


def test_health_returns_healthy_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "database_summary",
        lambda: {"assets": 6, "maintenance_events": 12},
    )

    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["assets"] == 6


def test_health_converts_database_failure_to_503(monkeypatch) -> None:
    def fail() -> None:
        raise RuntimeError("database is unavailable")

    monkeypatch.setattr(main, "database_summary", fail)

    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
