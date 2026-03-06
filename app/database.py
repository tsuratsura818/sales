from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import lead, search_job, email_log, follow_up, competitor, portfolio, job_listing, job_application, monitor_log, monitor_settings  # noqa: F401
    Base.metadata.create_all(bind=engine)
    if _is_sqlite:
        _migrate_sqlite()


def _migrate_sqlite():
    """既存SQLite DBに新規列を追加するマイグレーション"""
    new_columns = [
        ("search_jobs", "filter_http_only", "BOOLEAN DEFAULT 0"),
        ("search_jobs", "filter_no_mobile",  "BOOLEAN DEFAULT 0"),
        ("search_jobs", "filter_cms_list",   "TEXT"),
        ("search_jobs", "serpapi_calls_used","INTEGER DEFAULT 0"),
        ("leads", "has_og_image",       "BOOLEAN"),
        ("leads", "has_favicon",        "BOOLEAN"),
        ("leads", "has_table_layout",   "BOOLEAN"),
        ("leads", "missing_alt_count",  "INTEGER"),
        ("leads", "is_ec_site",         "BOOLEAN"),
        ("leads", "ec_platform",        "TEXT"),
        ("leads", "has_site_search",    "BOOLEAN"),
        ("leads", "has_product_schema", "BOOLEAN"),
        ("leads", "has_structured_data","BOOLEAN"),
        ("leads", "has_breadcrumb",     "BOOLEAN"),
        ("leads", "has_sitemap",        "BOOLEAN"),
        ("leads", "has_robots_txt",     "BOOLEAN"),
        ("leads", "followup_status",    "TEXT"),
        ("email_logs", "follow_up_step_id", "INTEGER"),
        ("leads", "has_contact_form",       "BOOLEAN"),
        ("leads", "form_field_count",       "INTEGER"),
        ("leads", "has_file_upload",        "BOOLEAN"),
        ("leads", "estimated_page_count",   "INTEGER"),
        ("leads", "company_size_estimate",  "TEXT"),
        ("leads", "industry_category",      "TEXT"),
        ("leads", "conversion_rank",        "TEXT"),
        ("leads", "meeting_scheduled_at",  "TIMESTAMP"),
        ("leads", "deal_closed_at",        "TIMESTAMP"),
        ("leads", "deal_amount",           "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, col, col_def in new_columns:
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
                ))
                conn.commit()
            except Exception:
                pass
