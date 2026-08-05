def test_deps_importable():
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
    import httpx  # noqa: F401
    from fastapi.testclient import TestClient  # noqa: F401
    assert True
