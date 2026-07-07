from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import engine

router = APIRouter(tags=["System"])


@router.get("/health")
def health_check() -> dict[str, str]:
    # Verifica a ligação à base de dados com uma query mínima, sem depender
    # de nenhuma tabela do domínio, para não falhar por motivos alheios à
    # disponibilidade da infraestrutura.
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from error

    return {
        "status": "ok",
        "database": "ok",
    }
