"""GET /api/v1/health/services.

Principle: boundary. Callers read status and the four service names.
embedding is reported and does not decide status.
"""

from fastapi.testclient import TestClient

from kbindex.api import create_app


class _Ping:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def ping(self) -> bool:
        if not self.ok:
            raise RuntimeError("down")
        return True


def _client(*, postgres: bool, redis_ok: bool, qdrant: bool, embedding: bool) -> TestClient:
    app = create_app()
    app.state.db = _Ping(postgres)
    app.state.redis = _Ping(redis_ok)
    app.state.vectors = _Ping(qdrant)
    app.state.embedder = object() if embedding else None
    return TestClient(app)


def test_health_services_is_healthy_when_the_three_stores_answer():
    response = _client(postgres=True, redis_ok=True, qdrant=True, embedding=True)
    body = response.get("/api/v1/health/services")
    assert body.status_code == 200
    assert body.json() == {
        "status": "healthy",
        "services": {
            "postgres": "healthy",
            "redis": "healthy",
            "qdrant": "healthy",
            "embedding": "healthy",
        },
    }


def test_health_services_stays_healthy_when_only_embedding_is_missing():
    body = _client(postgres=True, redis_ok=True, qdrant=True, embedding=False).get("/api/v1/health/services")
    assert body.status_code == 200
    payload = body.json()
    assert payload["status"] == "healthy"
    assert payload["services"]["embedding"] == "unhealthy"


def test_health_services_is_unhealthy_when_a_store_is_down():
    body = _client(postgres=False, redis_ok=True, qdrant=True, embedding=True).get("/api/v1/health/services")
    assert body.status_code == 200
    payload = body.json()
    assert payload["status"] == "unhealthy"
    assert payload["services"]["postgres"] == "unhealthy"
    assert payload["services"]["redis"] == "healthy"
    assert payload["services"]["qdrant"] == "healthy"
