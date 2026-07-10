from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.health import router as health_router
from app.api.routes.institutions import router as institutions_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.error_handlers import register_error_handlers

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)

register_error_handlers(app)

app.include_router(
    health_router,
    prefix="/api/v1",
)

app.include_router(
    institutions_router,
    prefix="/api/v1",
)

app.include_router(
    auth_router,
    prefix="/api/v1",
)

app.include_router(
    users_router,
    prefix="/api/v1",
)

app.include_router(
    conversations_router,
    prefix="/api/v1",
)
