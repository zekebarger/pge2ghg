import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Read the database URL from an environment variable.
# This is set in docker-compose.yml so the app knows how to find the Postgres container.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ghguser:ghgpassword@localhost:5432/ghgdb"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    """
    FastAPI dependency that provides a database session per request
    and ensures it's closed afterward — even if an error occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
