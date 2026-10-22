"""Criação de contas por papel para os testes, através da API real.

A gestão documental deixou de ser uma permissão implícita de ``admin`` e
passou a pertencer a ``knowledge_manager`` (ver ``app/core/permissions.py``).
Os testes que precisam de carregar documentos criam, por isso, um gestor
documental pela mesma via que uma instituição usaria: um admin autenticado
cria a conta com ``POST /users``. Nenhuma linha é inserida por baixo da API.
"""

import uuid

from fastapi.testclient import TestClient

ROLE_PASSWORD = "rolesecret123"


def create_account_and_login(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    role: str,
    full_name: str | None = None,
) -> tuple[dict[str, str], str]:
    """Cria uma conta com o papel indicado e devolve (headers, user_id)."""
    email = f"{role.replace('_', '-')}-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": full_name or f"Synthetic {role}",
            "email": email,
            "password": ROLE_PASSWORD,
            "role": role,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": ROLE_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, created.json()["id"]


def create_knowledge_manager(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    """Gestor documental da instituição do admin indicado."""
    headers, _ = create_account_and_login(client, admin_headers, role="knowledge_manager")
    return headers
