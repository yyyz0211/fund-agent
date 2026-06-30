from backend.db.session import Base, engine as default_engine
import backend.db.models  # noqa: F401  (register models)


def init_db(engine=None) -> None:
    Base.metadata.create_all(engine or default_engine)


if __name__ == "__main__":
    import os
    os.makedirs("backend/data", exist_ok=True)
    init_db()
    print("Tables created.")
