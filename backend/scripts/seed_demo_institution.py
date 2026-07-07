"""Idempotent seed: creates the generic demo institution if it doesn't exist.

Run from the backend directory (venv active):

    python -m scripts.seed_demo_institution
"""

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.institution import Institution
from app.schemas.institution import InstitutionCreate
from app.services import institution_service

DEMO_CODE = "DEMO-HEI"


def seed() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(Institution).where(Institution.code == DEMO_CODE))
        if existing is not None:
            print(f"Demo institution already exists (id={existing.id}). Nothing to do.")
            return

        # Reutiliza o serviço em vez de inserir diretamente com o ORM,
        # para que as mesmas regras de validação de domínio se apliquem.
        institution = institution_service.create_institution(
            db,
            InstitutionCreate(
                name="Demo Higher Education Institution",
                code=DEMO_CODE,
                domain=None,
                default_language="pt",
                supported_languages=["pt", "en"],
            ),
        )
        print(f"Demo institution created (id={institution.id}).")


if __name__ == "__main__":
    seed()
