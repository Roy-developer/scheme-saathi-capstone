import os

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ServiceInfo(BaseModel):
    name: str
    api_version: str
    app_version: str
    deployed_ref: str
    synthetic_only: bool


app = FastAPI(
    title="Scheme Saathi API",
    summary="Minimal shared backend foundation for Scheme Saathi.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse(status="healthy")


@app.get("/api/v1/info", response_model=ServiceInfo, tags=["service"])
def service_info() -> ServiceInfo:
    return ServiceInfo(
        name="scheme-saathi-api",
        api_version=app.version,
        app_version=os.getenv("APP_VERSION", "development"),
        deployed_ref=os.getenv("DEPLOYED_REF", "local"),
        synthetic_only=True,
    )
