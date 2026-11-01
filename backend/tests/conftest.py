from __future__ import annotations

from collections.abc import Generator
import os
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Tests never inherit real AI credentials or start a paid background worker.
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = ""
os.environ["JOB_WORKER_ENABLED"] = "false"

from app.api.deps import get_db
from app.core.database import Base
from app.main import app
from app import main
from app.services import storage


@pytest.fixture(autouse=True)
def forbid_external_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External HTTP is disabled in tests. Use a fake adapter or httpx.MockTransport.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def api_client(db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield db_session

    monkeypatch.setattr(storage, "settings", SimpleNamespace(resolved_upload_dir=tmp_path))
    monkeypatch.setattr(main.settings, "job_worker_enabled", False)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
