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
    # 生产环境必须显式配置前端来源，逗号分隔；开发环境为空时仅允许本地前端。
    cors_origins: str = ""

    # 数据库
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False  # 开发期临时查SQL才打开，否则终端日志2分钟刷200KB+，容易被杀/缓冲区撑死
    db_sql_log: bool = False  # 写入不含绑定参数的 SQL 与耗时，便于排查且避免记录学生数据

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
    api_key_encryption_key: str = ""

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
    # 教务助手模型服务的进程内熔断策略。多实例部署时会由 Redis 实现接管同一接口。
    assistant_provider_failure_threshold: int = 2
    assistant_provider_cooldown_seconds: float = 60.0
    assistant_embedding_model_path: str = ""

    # 对象存储 COS
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = "ap-guangzhou"
    cos_bucket: str = ""

    # MinIO（本地文件中心）
    minio_endpoint: str = "localhost:9010"
    minio_access_key: str = "lightclassroom"
    minio_secret_key: str = "lightclassroom"
    minio_bucket: str = "light-classroom"
    minio_secure: bool = False
    minio_public_base_url: str = "http://localhost:9010"

    # Celery + RabbitMQ
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"
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
