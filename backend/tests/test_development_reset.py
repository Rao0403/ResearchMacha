from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.models.paper import Paper
from scripts import reset_development as reset


def config(**changes):
    return Settings(_env_file=None, database_url="mysql+pymysql://root@127.0.0.1/research_macha", **changes)


@pytest.mark.parametrize("changes", [
    {"app_env": "production"},
    {"database_url": "mysql+pymysql://root@remote/research_macha"},
    {"database_url": "mysql+pymysql://root@localhost/mysql"},
    {"qdrant_url": "https://remote.example"},
    {"qdrant_collection": "unrelated"},
])
def test_reset_rejects_unsafe_targets(changes):
    values = {"database_url": "mysql+pymysql://root@127.0.0.1/research_macha", **changes}
    with pytest.raises(ValueError):
        reset.validate_target(Settings(_env_file=None, **values))


def test_reset_requires_exact_database_confirmation():
    assert reset.validate_target(config(), "research_macha") == "research_macha"
    with pytest.raises(ValueError, match="exactly match"):
        reset.validate_target(config(), "other")


def test_collection_scope_keeps_unrelated_vectors():
    names = ["research_macha_chunks", "research_macha_chunks_012345abcdef",
             "research_macha_memories_abcdef012345", "other", "research_macha_chunks_backup",
             "research_macha_chunks_012345abcdef_extra"]
    assert reset.matching_collections(names, ("research_macha_chunks", "research_macha_memories")) == sorted(names[:3])


def test_reset_clears_only_application_rows_and_keeps_schema(db_session):
    db_session.add(Paper(title="Old paper", source="upload", pdf_path="retained.pdf", status="ready"))
    db_session.commit()
    engine = db_session.get_bind()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unrelated (value INTEGER)"))
        connection.execute(text("INSERT INTO unrelated VALUES (42)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('head')"))
    assert reset.row_counts(engine)["papers"] == 1
    reset.clear_application_rows(engine)
    reset.clear_application_rows(engine)  # Safe to resume an interrupted reset.
    assert all(count == 0 for count in reset.row_counts(engine).values())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM unrelated")) == 42
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "head"


def test_cli_preview_never_mutates(monkeypatch, capsys):
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect_ex(self, address): return 1

    monkeypatch.setattr(reset, "get_settings", lambda: config(vector_provider="mysql"))
    monkeypatch.setattr(reset.socket, "socket", Probe)
    monkeypatch.setattr(reset, "create_engine", lambda *args, **kwargs: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(reset, "row_counts", lambda engine: {"papers": 3})
    monkeypatch.setattr(reset, "clear_application_rows", lambda engine: pytest.fail("Preview must not mutate"))
    assert reset.main([]) == 0
    assert "Preview only" in capsys.readouterr().out


def test_cli_apply_requires_confirmation_before_connections():
    with pytest.raises(SystemExit):
        reset.main(["--apply"])
