"""서비스 의존성 헬스체크."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.providers import HealthChecker, get_health_checker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(checker: HealthChecker = Depends(get_health_checker)) -> dict[str, object]:
    dependencies = dict(await checker.check())
    status = "ok" if all(value == "ok" for value in dependencies.values()) else "degraded"
    return {"status": status, "dependencies": dependencies}
