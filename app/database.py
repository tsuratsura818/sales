import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

log = logging.getLogger("database")
settings = get_settings()

# DATABASE_URLにパスワード内の@が含まれる場合のワークアラウンド
_db_url = settings.DATABASE_URL
if _db_url and not _db_url.startswith("sqlite") and "%" not in _db_url:
    # URLエンコードされていない@がパスワードに含まれている可能性
    pass

_is_sqlite = _db_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}

_pool_args = {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20, "pool_recycle": 300} if not _is_sqlite else {}
try:
    engine = create_engine(_db_url, connect_args=connect_args, **_pool_args)
except Exception as e:
    log.warning(f"DB接続URL解析エラー、SQLiteにフォールバック: {e}")
    _db_url = "sqlite:///./sales.db"
    _is_sqlite = True
    connect_args = {"check_same_thread": False}
    engine = create_engine(_db_url, connect_args=connect_args)


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
    from app.models import lead, search_job, email_log, follow_up, competitor, portfolio, job_listing, job_application, monitor_log, monitor_settings, daily_plan, memo, app_settings, goal, pipeline, inbound, pipeline_keyword, suppression  # noqa: F401
    try:
        Base.metadata.create_all(bind=engine)
        if _is_sqlite:
            _migrate_sqlite()
        else:
            _migrate_postgres()
        _seed_pipeline_keywords()
    except Exception as e:
        log.error(f"DB初期化エラー（アプリは継続起動）: {e}")


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
        ("search_jobs", "search_method",   "TEXT DEFAULT 'serpapi'"),
        ("leads", "probability",            "INTEGER"),
        ("leads", "deal_stage",             "TEXT"),
        ("leads", "lost_reason",            "TEXT"),
        ("leads", "expected_close_date",    "TIMESTAMP"),
        # pipeline v2: モード・カテゴリ・個別化提案文
        ("pipeline_runs", "mode",           "TEXT DEFAULT 'ec'"),
        ("pipeline_runs", "category_config","TEXT"),
        ("pipeline_results", "category",    "TEXT"),
        ("pipeline_results", "confidence",  "REAL"),
        ("pipeline_results", "personalized_subject", "TEXT"),
        ("pipeline_results", "personalized_body",    "TEXT"),
        ("pipeline_results", "site_analysis",        "TEXT"),
        # 単発検索の自動提案文生成設定
        ("search_jobs", "auto_generate_proposal",   "BOOLEAN DEFAULT 1"),
        ("search_jobs", "auto_proposal_min_score",  "INTEGER DEFAULT 50"),
        # PipelineResult 昇格リード向け
        ("leads", "pipeline_result_id",             "INTEGER"),
        # メールトラッキング (Phase 6)
        ("email_logs", "tracking_id",               "TEXT"),
        ("email_logs", "opened_at",                 "TIMESTAMP"),
        ("email_logs", "open_count",                "INTEGER DEFAULT 0"),
        ("email_logs", "clicked_at",                "TIMESTAMP"),
        ("email_logs", "click_count",               "INTEGER DEFAULT 0"),
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

        # search_job_id を NULL 許容に変更 (SQLite は NOT NULL 制約変更が難しいので skip)
        # 既存データは search_job_id があるので問題なし。新規 INSERT のみ NULL を許可。
        # (SQLAlchemy 側の nullable=True で対応するため、SQLite 側の制約は形式上残ってもOK)


def _migrate_postgres():
    """既存PostgreSQL DBに新規列を追加するマイグレーション"""
    new_columns = [
        ("search_jobs", "search_method", "TEXT DEFAULT 'serpapi'"),
        ("leads", "probability", "INTEGER"),
        ("leads", "deal_stage", "TEXT"),
        ("leads", "lost_reason", "TEXT"),
        ("leads", "expected_close_date", "TIMESTAMP"),
        # pipeline v2
        ("pipeline_runs", "mode", "TEXT DEFAULT 'ec'"),
        ("pipeline_runs", "category_config", "TEXT"),
        ("pipeline_results", "category", "TEXT"),
        ("pipeline_results", "confidence", "DOUBLE PRECISION"),
        ("pipeline_results", "personalized_subject", "TEXT"),
        ("pipeline_results", "personalized_body", "TEXT"),
        ("pipeline_results", "site_analysis", "TEXT"),
        # 単発検索の自動提案文生成設定
        ("search_jobs", "auto_generate_proposal", "BOOLEAN DEFAULT TRUE"),
        ("search_jobs", "auto_proposal_min_score", "INTEGER DEFAULT 50"),
        # PipelineResult 昇格リード向け
        ("leads", "pipeline_result_id", "INTEGER"),
        # メールトラッキング (Phase 6)
        ("email_logs", "tracking_id",  "TEXT"),
        ("email_logs", "opened_at",    "TIMESTAMP"),
        ("email_logs", "open_count",   "INTEGER DEFAULT 0"),
        ("email_logs", "clicked_at",   "TIMESTAMP"),
        ("email_logs", "click_count",  "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col, col_def in new_columns:
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def}"
                ))
                conn.commit()
            except Exception:
                pass

        # search_job_id を NULL 許容に変更
        try:
            conn.execute(text("ALTER TABLE leads ALTER COLUMN search_job_id DROP NOT NULL"))
            conn.commit()
        except Exception:
            pass

        # app_settings 初期行（daily_plan_enabled=FALSE で停止状態）
        try:
            result = conn.execute(text("SELECT COUNT(*) FROM app_settings"))
            if result.scalar() == 0:
                conn.execute(text(
                    "INSERT INTO app_settings (daily_plan_enabled, daily_plan_hour_jst) VALUES (FALSE, 8)"
                ))
                conn.commit()
        except Exception:
            pass


def _seed_pipeline_keywords():
    """pipeline_keywordsテーブルが空なら、デフォルトキーワードをシード"""
    from app.models.pipeline_keyword import PipelineKeyword
    from app.services.pipeline.config import SEARCH_KEYWORDS
    db = SessionLocal()
    try:
        count = db.query(PipelineKeyword).count()
        if count > 0:
            return
        for keyword, industry in SEARCH_KEYWORDS:
            db.add(PipelineKeyword(keyword=keyword, industry=industry, source="all", enabled=1))
        db.commit()
        log.info(f"パイプラインキーワード {len(SEARCH_KEYWORDS)}件をシード")
    except Exception as e:
        log.warning(f"キーワードシードエラー: {e}")
        db.rollback()
    finally:
        db.close()
