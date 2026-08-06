import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import settings
# pyrefly: ignore [missing-import]
from app.models.db_models import Base

logger = logging.getLogger(__name__)

# Engine setup
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def auto_migrate():
    """Auto-migrates existing database tables by adding missing enterprise columns."""
    if "sqlite" not in settings.DATABASE_URL:
        return

    try:
        with engine.connect() as conn:
            # 1. Migrate persons table
            res = conn.execute(text("PRAGMA table_info(persons)")).fetchall()
            cols = {row[1] for row in res} if res else set()
            if cols:
                if "first_name" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN first_name VARCHAR(100)"))
                if "last_name" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN last_name VARCHAR(100)"))
                if "department" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN department VARCHAR(100)"))
                if "role" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN role VARCHAR(100)"))
                if "phone" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN phone VARCHAR(50)"))
                if "email" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN email VARCHAR(100)"))
                if "company" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN company VARCHAR(200)"))
                if "notes" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN notes VARCHAR(1000)"))
                if "gallery_version" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN gallery_version INTEGER DEFAULT 1"))
                if "source_candidate_id" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN source_candidate_id VARCHAR(100)"))
                if "updated_at" not in cols:
                    conn.execute(text("ALTER TABLE persons ADD COLUMN updated_at DATETIME"))
                conn.commit()

            # 1b. Migrate person_images table
            res = conn.execute(text("PRAGMA table_info(person_images)")).fetchall()
            p_cols = {row[1] for row in res} if res else set()
            if p_cols:
                if "yaw" not in p_cols:
                    conn.execute(text("ALTER TABLE person_images ADD COLUMN yaw FLOAT DEFAULT 0.0"))
                if "pitch" not in p_cols:
                    conn.execute(text("ALTER TABLE person_images ADD COLUMN pitch FLOAT DEFAULT 0.0"))
                if "brightness" not in p_cols:
                    conn.execute(text("ALTER TABLE person_images ADD COLUMN brightness FLOAT DEFAULT 0.0"))
                if "blur_score" not in p_cols:
                    conn.execute(text("ALTER TABLE person_images ADD COLUMN blur_score FLOAT DEFAULT 0.0"))
                if "camera_id" not in p_cols:
                    conn.execute(text("ALTER TABLE person_images ADD COLUMN camera_id VARCHAR(100) DEFAULT 'default'"))
                conn.commit()

            # 2. Migrate embeddings table
            res = conn.execute(text("PRAGMA table_info(embeddings)")).fetchall()
            cols = {row[1] for row in res} if res else set()
            if cols:
                if "image_id" not in cols:
                    conn.execute(text("ALTER TABLE embeddings ADD COLUMN image_id INTEGER"))
                if "gallery_version" not in cols:
                    conn.execute(text("ALTER TABLE embeddings ADD COLUMN gallery_version INTEGER DEFAULT 1"))
                if "is_active" not in cols:
                    conn.execute(text("ALTER TABLE embeddings ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                if "archived_at" not in cols:
                    conn.execute(text("ALTER TABLE embeddings ADD COLUMN archived_at DATETIME"))
                conn.commit()

            # 3. Migrate recognition_logs table
            res = conn.execute(text("PRAGMA table_info(recognition_logs)")).fetchall()
            cols = {row[1] for row in res} if res else set()
            if cols:
                if "camera_id" not in cols:
                    conn.execute(text("ALTER TABLE recognition_logs ADD COLUMN camera_id VARCHAR(100) DEFAULT 'default'"))
                if "embedding_version" not in cols:
                    conn.execute(text("ALTER TABLE recognition_logs ADD COLUMN embedding_version INTEGER DEFAULT 1"))
                if "quality_score" not in cols:
                    conn.execute(text("ALTER TABLE recognition_logs ADD COLUMN quality_score FLOAT DEFAULT 0.0"))
                if "face_snapshot_path" not in cols:
                    conn.execute(text("ALTER TABLE recognition_logs ADD COLUMN face_snapshot_path VARCHAR(500)"))
                conn.commit()

            logger.info("Database schema auto-migration completed successfully.")
    except Exception as e:
        logger.error(f"Error during database auto-migration: {e}")

def init_db():
    """Create all database tables and apply schema migrations."""
    Base.metadata.create_all(bind=engine)
    auto_migrate()

def get_db():
    """Dependency helper for database session context."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
