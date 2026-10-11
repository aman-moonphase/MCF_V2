from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db import base as _orm_models  # noqa: F401  (registers every ORM model so string relationships resolve)
from app.api.routes import projects, workflow_stages, health, ai, sources, schedules, diagnostics, auth, products, competitors, strategy, generation, evaluation, content_planning, user_settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])
app.include_router(sources.router, prefix=f"{settings.API_V1_STR}/projects", tags=["sources"])
app.include_router(workflow_stages.router, prefix=f"{settings.API_V1_STR}/projects", tags=["workflow_stages"])
app.include_router(products.project_router, prefix=f"{settings.API_V1_STR}/projects", tags=["products"])
app.include_router(products.router, prefix=f"{settings.API_V1_STR}/products", tags=["products"])
app.include_router(competitors.router, prefix=f"{settings.API_V1_STR}/products", tags=["competitors"])
app.include_router(strategy.router, prefix=f"{settings.API_V1_STR}/products", tags=["promotion-strategy"])
app.include_router(generation.router, prefix=f"{settings.API_V1_STR}/projects", tags=["generate-content"])
app.include_router(evaluation.router, prefix=f"{settings.API_V1_STR}/projects", tags=["evaluate-improve"])
app.include_router(ai.router, prefix=f"{settings.API_V1_STR}/ai", tags=["ai"])
app.include_router(schedules.router, prefix=f"{settings.API_V1_STR}/schedules", tags=["schedules"])
app.include_router(content_planning.router, prefix=settings.API_V1_STR, tags=["content-planning"])
app.include_router(diagnostics.router, prefix=f"{settings.API_V1_STR}/diagnostics", tags=["diagnostics"])
app.include_router(user_settings.router, prefix=f"{settings.API_V1_STR}/settings", tags=["settings"])
