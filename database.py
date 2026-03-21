"""Database engine and session configuration for BotNode.

Provides a SQLAlchemy engine (with PostgreSQL connection-pool tuning for
production) and a ``get_db`` dependency suitable for FastAPI route injection.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

# Database URL from environment or fallback to SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./botnode.db")

# For PostgreSQL, we need to handle the URL slightly differently if it's async or has specific requirements
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Route through PgBouncer (port 6432) when available, keeping direct PostgreSQL as fallback
PGBOUNCER_URL = os.getenv("PGBOUNCER_URL", "")
if PGBOUNCER_URL:
    if PGBOUNCER_URL.startswith("postgres://"):
        PGBOUNCER_URL = PGBOUNCER_URL.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = PGBOUNCER_URL

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Use row-level locking for financial integrity (PostgreSQL)
    engine_kwargs["isolation_level"] = "READ COMMITTED"
    engine_kwargs["pool_pre_ping"] = True
    # When using PgBouncer in transaction mode, keep the application-side pool
    # modest since PgBouncer handles connection multiplexing
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 30
    engine_kwargs["pool_timeout"] = 10

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Yield a SQLAlchemy session, auto-closed on request completion."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
