from fastapi.testclient import TestClient

# Test the health endpoint
def test_health_endpoint_returns_database_status(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    
    # Assert that the response status code is 200 and the response body contains the expected database status
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
    }
