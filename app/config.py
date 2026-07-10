import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value")


def _get_int(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be greater than or equal to {minimum}")
    return value


def _resolve_path(raw_value: str | None, default: Path) -> Path:
    path = Path(raw_value).expanduser() if raw_value else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _normalize_database_url(raw_url: str | None) -> str:
    if not raw_url:
        return f"sqlite:///{(BASE_DIR / 'blog.db').resolve()}"

    # SQLAlchemy 的 sqlite:///relative.db 相对于进程工作目录。统一锚定项目根目录，
    # 避免由 systemd、Docker 或手工启动目录不同而误连到另一份空数据库。
    prefix = "sqlite:///"
    if raw_url.startswith(prefix) and not raw_url.startswith("sqlite:////"):
        database_path = raw_url[len(prefix):]
        if database_path != ":memory:" and "?" not in database_path:
            return f"sqlite:///{_resolve_path(database_path, BASE_DIR / 'blog.db')}"
    return raw_url


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
if APP_ENV == "testing":
    APP_ENV = "test"
if APP_ENV not in {"local", "development", "test", "production"}:
    raise RuntimeError("APP_ENV must be one of local, development, test/testing, production")
IS_PRODUCTION = APP_ENV == "production"

DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))

DEFAULT_SECRET_KEY = "unrecycle_super_secret_key_change_me_in_production"
DEFAULT_ADMIN_PASSWORD = "admin123"

SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "unrecycle-me")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "unrecycle-me-admin")
TOKEN_VERSION = os.getenv("TOKEN_VERSION", "1").strip()
JWT_LEEWAY_SECONDS = _get_int("JWT_LEEWAY_SECONDS", 30, minimum=0)
ACCESS_TOKEN_EXPIRE_MINUTES = _get_int(
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    60 * 24 * 7,
    minimum=1,
)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

COOKIE_SECURE = _get_bool("COOKIE_SECURE", IS_PRODUCTION)
COOKIE_SAMESITE = os.getenv(
    "COOKIE_SAMESITE", "strict" if IS_PRODUCTION else "lax"
).strip().lower()
if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise RuntimeError("COOKIE_SAMESITE must be lax, strict or none")
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    raise RuntimeError("COOKIE_SECURE must be enabled when COOKIE_SAMESITE=none")
COOKIE_NAME = os.getenv(
    "COOKIE_NAME", "__Host-admin_session" if COOKIE_SECURE else "access_token"
).strip()

LOGIN_RATE_LIMIT_ATTEMPTS = _get_int("LOGIN_RATE_LIMIT_ATTEMPTS", 5, minimum=1)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = _get_int(
    "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300, minimum=1
)

STATIC_DIR = (BASE_DIR / "app" / "static").resolve()
TEMPLATE_DIR = (BASE_DIR / "app" / "templates").resolve()
UPLOAD_DIR = _resolve_path(os.getenv("UPLOAD_DIR"), STATIC_DIR / "uploads")
MAX_UPLOAD_BYTES = _get_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024, minimum=1024)
UPLOAD_CHUNK_SIZE = _get_int("UPLOAD_CHUNK_SIZE", 1024 * 1024, minimum=4096)

SQLITE_BUSY_TIMEOUT_MS = _get_int("SQLITE_BUSY_TIMEOUT_MS", 5000, minimum=100)
SEED_INITIAL_DATA = _get_bool("SEED_INITIAL_DATA", not IS_PRODUCTION)
RUN_LEGACY_COMPAT_MIGRATION = _get_bool("RUN_LEGACY_COMPAT_MIGRATION", False)
ENABLE_DOCS = _get_bool("ENABLE_DOCS", not IS_PRODUCTION)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    markers = (
        "change_me",
        "change-me",
        "generate_a_secure",
        "placeholder",
        "your_secret",
    )
    return any(marker in lowered for marker in markers)


def _validate_security_configuration() -> None:
    if not ADMIN_USERNAME:
        raise RuntimeError("ADMIN_USERNAME must not be empty")
    if not TOKEN_VERSION:
        raise RuntimeError("TOKEN_VERSION must not be empty")
    if len(ADMIN_PASSWORD.encode("utf-8")) > 72:
        raise RuntimeError("ADMIN_PASSWORD must be at most 72 UTF-8 bytes for bcrypt")

    if not IS_PRODUCTION:
        return

    problems: list[str] = []
    if SECRET_KEY == DEFAULT_SECRET_KEY or _looks_like_placeholder(SECRET_KEY):
        problems.append("SECRET_KEY is still a default or placeholder value")
    if len(SECRET_KEY.encode("utf-8")) < 32:
        problems.append("SECRET_KEY must contain at least 32 UTF-8 bytes")
    if ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD or _looks_like_placeholder(ADMIN_PASSWORD):
        problems.append("ADMIN_PASSWORD is still a default or placeholder value")
    if len(ADMIN_PASSWORD) < 12:
        problems.append("ADMIN_PASSWORD must contain at least 12 characters")
    if not COOKIE_SECURE:
        problems.append("COOKIE_SECURE must be enabled in production")

    if problems:
        details = "; ".join(problems)
        raise RuntimeError(f"Unsafe production configuration: {details}")


_validate_security_configuration()
