import importlib
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_bundle(tmp_path, monkeypatch):
    """为每个测试导入一份绑定临时数据库和上传目录的应用。"""

    upload_dir = tmp_path / "uploads"
    database_path = tmp_path / "blog-test.db"

    test_environment = {
        "APP_ENV": "test",
        "SECRET_KEY": "integration-test-secret-key-0123456789abcdef0123456789abcdef",
        "ADMIN_USERNAME": "test-admin",
        "ADMIN_PASSWORD": "test-admin-password-2026",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "UPLOAD_DIR": str(upload_dir),
        "COOKIE_SECURE": "true",
        "COOKIE_SAMESITE": "strict",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "10080",
        "LOGIN_RATE_LIMIT_ATTEMPTS": "100",
        "LOGIN_RATE_LIMIT_WINDOW_SECONDS": "60",
        "MAX_UPLOAD_BYTES": "1024",
        "UPLOAD_CHUNK_SIZE": "4096",
        "SQLITE_BUSY_TIMEOUT_MS": "1000",
        "SEED_INITIAL_DATA": "false",
        "RUN_LEGACY_COMPAT_MIGRATION": "false",
        "ENABLE_DOCS": "false",
        "TOKEN_VERSION": "integration-tests",
    }
    for name, value in test_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("COOKIE_NAME", raising=False)

    # 配置在模块导入期读取。清理缓存可确保每个测试只连接自己的 tmp_path。
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)

    main = importlib.import_module("app.main")
    auth = importlib.import_module("app.auth")
    config = importlib.import_module("app.config")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")

    with TestClient(main.app, base_url="https://testserver") as client:
        yield SimpleNamespace(
            app=main.app,
            auth=auth,
            client=client,
            config=config,
            database=database,
            database_path=database_path,
            main=main,
            models=models,
            upload_dir=upload_dir,
        )

    database.engine.dispose()
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


@pytest.fixture
def authenticated_client(app_bundle):
    response = app_bundle.client.post(
        "/api/auth/login",
        json={
            "username": "test-admin",
            "password": "test-admin-password-2026",
        },
    )
    assert response.status_code == 200, response.text
    return app_bundle.client
