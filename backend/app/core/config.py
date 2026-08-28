"""应用配置 - 基于 pydantic-settings，环境变量加载"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_name: str = "轻课堂"
    app_env: str = "dev"
    app_debug: bool = True
    default_school_code: str = "demo"  # 私有化部署固定单值

    # 数据库
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False  # 开发期临时查SQL才打开，否则终端日志2分钟刷200KB+，容易被杀/缓冲区撑死

    # Redis
    redis_url: str

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_grading: str = "grading-events"
    kafka_topic_practice: str = "practice-events"
    kafka_topic_prediction: str = "prediction-events"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # 平台超管（创建学校的运营后台）
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_name: str = "平台管理员"

    # LLM（OpenAI 兼容协议，可配 DeepSeek/GLM/通义）
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 4096
    llm_cost_limit_per_sheet: float = 0.5  # 成本红线

    # 对象存储 COS
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = "ap-guangzhou"
    cos_bucket: str = ""

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # A5 限流（开发期内存实现；B4 接入 Redis 后切换为分布式计数）
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 300  # 窗口内每客户端/IP 上限（报到日/考试周按需调大）

    # 审计日志：默认只记录写操作（POST/PUT/PATCH/DELETE）
    audit_enabled: bool = True
    audit_log_mutations_only: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
