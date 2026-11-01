from __future__ import annotations

from app.core.database import SessionLocal
from app.services.research import seed_demo_project


def main() -> None:
    db = SessionLocal()
    try:
        project = seed_demo_project(db)
        print("Seeded demo research project")
        print(f"Project id: {project.id}")
        print(f"Question: {project.question}")
        print("Open the frontend and visit /debug/projects or start a new Research workflow.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
