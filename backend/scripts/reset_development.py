"""Explicit, local-only development reset. Never imports or invokes an AI provider."""
from __future__ import annotations

import argparse
import re
import socket
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine, make_url

from app.core.config import Settings, get_settings
from app.core.database import Base
from app.models import paper as _models  # Register every application table.


def validate_target(settings: Settings, confirmation: str | None = None) -> str:
    url = make_url(settings.resolved_database_url)
    name = url.database or ""
    if settings.app_env != "development":
        raise ValueError("Reset is available only with APP_ENV=development.")
    if url.get_backend_name() != "mysql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Reset requires a local MySQL database.")
    if not re.fullmatch(r"research_macha(?:_[a-zA-Z0-9_]+)?", name):
        raise ValueError("Database name must be research_macha or start with research_macha_.")
    if confirmation is not None and confirmation != name:
        raise ValueError("--confirm must exactly match the configured database name.")
    if settings.vector_provider == "qdrant":
        if urlparse(settings.qdrant_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Reset requires a local Qdrant instance.")
        bases = (settings.qdrant_collection, settings.qdrant_memory_collection)
        if any(not base.startswith("research_macha_") for base in bases):
            raise ValueError("Qdrant collection bases must start with research_macha_.")
    return name


def matching_collections(names: list[str], bases: tuple[str, str]) -> list[str]:
    return sorted(name for name in names if any(
        re.fullmatch(re.escape(base) + r"(?:_[a-f0-9]{12})?", name) for base in bases
    ))


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {table.name: connection.scalar(select(func.count()).select_from(table)) or 0
                for table in Base.metadata.sorted_tables}


def clear_application_rows(engine: Engine) -> None:
    # Keep the schema, Alembic revision, and any unrelated tables intact.
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Clear local ResearchMacha development rows and configured vector collections. "
        "Default: preview only. Uploaded PDF files and .env are retained. No AI requests. "
        "Stop the backend first and run Alembic upgrade head before resetting."
    ))
    parser.add_argument("--apply", action="store_true", help="Actually clear development data.")
    parser.add_argument("--confirm", help="Required with --apply: exact configured database name.")
    args = parser.parse_args(argv)
    if args.apply and not args.confirm:
        parser.error("--apply requires --confirm DATABASE_NAME")
    settings = get_settings()
    try:
        database = validate_target(settings, args.confirm)
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", settings.api_port)) == 0:
                raise ValueError("Stop the backend before previewing or applying a reset.")
    except ValueError as error:
        parser.error(str(error))

    engine = create_engine(settings.resolved_database_url, pool_pre_ping=True)
    client = None
    try:
        print(f"Local database: {database}")
        for table, count in row_counts(engine).items():
            print(f"  {table}: {count} rows")
        collections: list[str] = []
        if settings.vector_provider == "qdrant":
            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=5)
            collections = matching_collections(
                [item.name for item in client.get_collections().collections],
                (settings.qdrant_collection, settings.qdrant_memory_collection),
            )
        print(f"Vector collections: {', '.join(collections) or '(none)'}")
        if not args.apply:
            print(f"Preview only. To apply: --apply --confirm {database}")
            return 0
        # The two stores cannot share a transaction; rerunning after interruption is safe.
        for name in collections:
            if not client.delete_collection(name):
                raise RuntimeError("Qdrant did not acknowledge collection deletion.")
        clear_application_rows(engine)
        print("Development rows and selected vectors cleared. PDF files and configuration retained.")
        return 0
    except Exception as error:
        print(f"Reset stopped ({type(error).__name__}). Check services and migrations, then rerun. "
              "Some vector collections may already have been cleared; SQL deletes are transactional.")
        return 1
    finally:
        if client is not None:
            client.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
