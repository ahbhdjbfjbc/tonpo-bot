# fx/database/database.py
"""
Database connection manager and session handling
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Generator, Optional
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# SQLAlchemy Base (moved from models to avoid circular imports)
Base = declarative_base()

class DatabaseManager:
    """
    Manages database connections and sessions with connection pooling
    """
    
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self._initialized = False
    
    def initialize(self, database_url: Optional[str] = None):
        """
        Initialize database connection with connection pooling
        
        Args:
            database_url: Database connection string. If None, uses DATABASE_URL env var
        """
        if self._initialized:
            logger.warning("Database already initialized")
            return
        
        # Get database URL from environment if not provided
        db_url = database_url or os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL must be set in environment or provided")
        
        # Handle Heroku's postgres:// vs postgresql://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        # SQLAlchemy 2.1 defaults generic PostgreSQL URLs to psycopg (v3).
        # The project supports psycopg2-binary instead, including on Termux.
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        
        # Never log full DSN (may contain credentials); host/path only.
        safe_target = db_url.split("@")[-1] if "@" in db_url else db_url.split("://")[-1][:80]
        logger.info("Initializing database connection to %s", safe_target)

        # SQLite cannot use QueuePool reliably (threading / :memory: issues).
        # PostgreSQL keeps the existing pooled configuration.
        is_sqlite = db_url.startswith("sqlite:")
        engine_kwargs = {
            "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
        }
        if is_sqlite:
            from sqlalchemy.pool import StaticPool
            engine_kwargs.update({
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            })
        else:
            engine_kwargs.update({
                "poolclass": QueuePool,
                "pool_size": 20,
                "max_overflow": 10,
                "pool_pre_ping": True,
                "pool_recycle": 3600,
            })

        self.engine = create_engine(db_url, **engine_kwargs)
        
        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
        self._initialized = True
        logger.info("Database initialized successfully")
    
    def create_tables(self):
        """Create all tables defined in models"""
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=self.engine)
        logger.info("Tables created successfully")
    
    def drop_tables(self):
        """Drop all tables (USE WITH CAUTION - for testing only)"""
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        logger.warning("DROPPING ALL TABLES! This should only be used in development.")
        Base.metadata.drop_all(bind=self.engine)
    
    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions
        
        Usage:
            with db_manager.session() as session:
                session.query(User).all()
        """
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        db_session = self.SessionLocal()
        try:
            yield db_session
            db_session.commit()
        except Exception as e:
            db_session.rollback()
            logger.error("Database session error (%s)", type(e).__name__)
            raise
        finally:
            db_session.close()
    
    def get_session(self) -> Session:
        """
        Get a new database session (for dependency injection)
        
        Usage:
            session = db_manager.get_session()
            try:
                # do work
                session.commit()
            finally:
                session.close()
        """
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        return self.SessionLocal()
    
    def close(self):
        """Close all database connections"""
        if self.engine:
            self.engine.dispose()
            logger.info("Database connections closed")


# Create global database manager instance
db_manager = DatabaseManager()


# Dependency for FastAPI/other frameworks
def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions
    
    Usage:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    """
    with db_manager.session() as session:
        yield session
