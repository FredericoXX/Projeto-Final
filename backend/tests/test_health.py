from fastapi.testclient import TestClient


def test_health_endpoint_returns_database_status(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    # Verifica se a API responde com sucesso e se a base de dados
    # está disponível no health check.
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
    }
