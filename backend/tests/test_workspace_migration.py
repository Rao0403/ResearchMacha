from sqlalchemy import create_engine, inspect, text

from test_reliability_migration import upgrade_database


def test_workspace_migration_preserves_legacy_chat_and_adds_tables(monkeypatch, tmp_path):
    path = tmp_path / "workspace.db"
    upgrade_database(monkeypatch, path, "20260925_0005")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as db:
        db.execute(text("INSERT INTO papers (id,source,title,authors,pdf_path,status,created_at,updated_at) VALUES ('p','upload','Keep','[]','keep.pdf','ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO chat_sessions (id,paper_id,title,created_at,updated_at) VALUES ('s','p','Chat',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        for ident, role in [("a", "assistant"), ("u", "user")]:
            db.execute(text("INSERT INTO chat_messages (id,session_id,role,content,citations,created_at) VALUES (:id,'s',:role,'Keep me','[]',CURRENT_TIMESTAMP)"), {"id":ident,"role":role})
    upgrade_database(monkeypatch, path)
    tables = inspect(engine).get_table_names()
    assert {"comparisons", "comparison_papers", "paper_reading_states", "paper_notes"} <= set(tables)
    with engine.connect() as db:
        assert db.execute(text("SELECT role,position,status,content FROM chat_messages ORDER BY position")).all() == [
            ("user", 0, "completed", "Keep me"), ("assistant", 1, "completed", "Keep me")]
        assert db.scalar(text("SELECT title FROM papers WHERE id='p'")) == "Keep"
    assert "comparison_id" in {c["name"] for c in inspect(engine).get_columns("jobs")}
    engine.dispose()
