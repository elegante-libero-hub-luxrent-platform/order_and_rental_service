import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Environment variables for DB connection
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "orders")

# Cloud SQL instance name for Unix socket
INSTANCE_CONNECTION_NAME = os.getenv("INSTANCE_CONNECTION_NAME")  # project:region:instance

# Detect if running on Cloud Run
RUNNING_IN_CLOUD = INSTANCE_CONNECTION_NAME is not None

# Choose connection method automatically
if RUNNING_IN_CLOUD:
    # Cloud Run → Use Unix Socket
    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASS}"
        f"@/{DB_NAME}?unix_socket=/cloudsql/{INSTANCE_CONNECTION_NAME}"
    )
    print("Using Cloud SQL Unix Socket connection")
else:
    # Local development → Use TCP connection
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = os.getenv("DB_PORT", "3306")

    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASS}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    print(f"Using local TCP MySQL connection at {DB_HOST}:{DB_PORT}")

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,  # helps prevent stale connections
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    """
    Dependency injection for FastAPI routes.
    Automatically handles session lifecycle.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
