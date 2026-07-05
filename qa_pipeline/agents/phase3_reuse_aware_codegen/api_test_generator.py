from __future__ import annotations


def plan_api_tests(openapi_path: str | None = None) -> dict:
    return {"status": "planned", "openapi_path": openapi_path, "message": "API Test Generator stub is registered for future OpenAPI/Swagger support."}
