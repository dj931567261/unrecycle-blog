# Unrecycle-Me 个人博客

Unrecycle-Me 是一个基于 FastAPI、SQLite、Jinja2 和原生 JavaScript 的个人数字主页，包含技术博客、网址导航、书签收藏和本地工具箱。

> 原游戏中心、兑换码和概率掉落功能已经移除，不属于当前可用功能。

## 当前功能

- 博客文章阅读、Markdown 渲染、代码高亮、阅读量统计与发布状态管理。
- 网址导航按分类展示与后台管理。
- 书签收藏的新增、编辑、删除、标签聚合和前端即时筛选。
- 博客、收藏及后台内容列表支持分页浏览。
- JSON、Base64、URL、Unicode、时间戳、卦象密码及图片背景处理等工具页面。
- 单管理员后台，使用 bcrypt 校验密码和 JWT HttpOnly Cookie 保持会话。
- 图片上传及 Markdown 编辑器中的拖拽、粘贴上传。
- 深色/浅色主题、响应式布局和文章图片灯箱。

## 环境要求

- Python 3.11
- Docker 与 Docker Compose v2（容器部署时）
- SQLite 数据库由应用自动创建

生产直接依赖已在 `requirements.txt` 中固定到验证版本；测试依赖位于
`requirements-dev.txt`。如需字节级可复现构建，还应使用带 hash 的完整 lock 文件，
并固定 Python 基础镜像 digest。

## 安全配置

1. 复制环境变量模板：

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

2. 生成独立密钥和管理员密码：

   ```bash
   openssl rand -hex 32
   openssl rand -base64 32
   ```

3. 将输出分别写入 `.env` 的 `SECRET_KEY` 和 `ADMIN_PASSWORD`，并填写小写的 `GHCR_OWNER`。

Compose 会拒绝缺少 `GHCR_OWNER`、`SECRET_KEY` 或 `ADMIN_PASSWORD` 的配置。不要使用项目历史默认密码、示例字符串或重复使用其他系统的密钥，也不要提交 `.env`。

重要环境变量：

- `SECRET_KEY`：JWT 签名密钥，生产必填。
- `ADMIN_USERNAME`、`ADMIN_PASSWORD`：后台管理员凭据，密码生产必填。
- `APP_ENV`：生产环境使用 `production`。
- `COOKIE_SECURE`：生产 HTTPS 环境必须为 `true`。
- `COOKIE_SAMESITE`：生产默认 `strict`。
- `ACCESS_TOKEN_EXPIRE_MINUTES`：管理员会话有效期，默认 10080 分钟（7 天）。
- `LOGIN_RATE_LIMIT_ATTEMPTS`、`LOGIN_RATE_LIMIT_WINDOW_SECONDS`：登录限流阈值与窗口。
- `MAX_UPLOAD_BYTES`：单文件上传上限，默认 10 MiB。
- `SQLITE_BUSY_TIMEOUT_MS`：SQLite 写锁等待时间，默认 5000 毫秒。
- `SEED_INITIAL_DATA`：是否在空表中写入初始示例数据。生产环境默认关闭；仅首次初始化需要示例数据时临时开启一次，随后应恢复为 `false`。
- `RUN_LEGACY_COMPAT_MIGRATION`：旧数据库兼容迁移开关，默认关闭；仅在备份后按升级说明临时启用。
- `ENABLE_DOCS`：生产默认关闭 OpenAPI 文档。
- `GHCR_OWNER`：GitHub 用户名或组织名，用于拼接 GHCR 镜像地址。
- `IMAGE_TAG`：默认 `latest`，回滚时建议改为具体 commit SHA。
- `BIND_ADDRESS`、`APP_PORT`：默认仅监听宿主 `127.0.0.1:8000`。
- `DATA_DIR`、`UPLOADS_DIR`：宿主持久化目录。
- `DATABASE_URL`：直接运行 Python 时可覆盖；生产 Compose 固定使用
  `/app/data/blog.db`，以确保备份和恢复命令不会操作错数据库。

## 本地开发

创建虚拟环境并安装测试依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements-dev.txt
```

`.env` 由 Docker Compose 自动读取；直接运行 Python 时需要显式导出变量。开发环境通过 HTTP 访问，因此应临时关闭 Secure Cookie：

```bash
set -a
source .env
set +a
APP_ENV=development COOKIE_SECURE=false ENABLE_DOCS=true python run.py
```

访问地址：

- 首页：<http://127.0.0.1:8000/>
- 管理入口：<http://127.0.0.1:8000/admin>
- OpenAPI：<http://127.0.0.1:8000/docs>

应用启动时会创建缺失的数据库表。仅当 `SEED_INITIAL_DATA=true` 时，导航、文章或书签整表为空才会写入初始示例数据；生产默认关闭该行为。升级或清空数据前请先备份。

## 测试与静态检查

```bash
ruff check . --select E9,F63,F7,F82
python -m pytest -q --timeout=60
```

CI 会在 pull request 和 `main` push 时依次执行 Ruff、pytest、Docker 镜像构建和容器烟测。
烟测会检查健康接口、首页、登录页、生产 Cookie 以及持久化目录写权限。只有全部通过，
`main` 分支才会把**刚刚通过测试的同一镜像**发布到 GHCR，并同时生成 `latest` 与
commit SHA 标签，不会在发布前重新构建。

## Docker 部署

生产 Compose 只拉取 CI 已验证的 GHCR 镜像，不会在服务器上从源码重新构建。
首次部署先加载 `.env` 并创建持久化目录。镜像使用 UID/GID `10001` 的非 root 用户；
Linux 服务器需确保自定义目录同样可写：

```bash
set -a
source .env
set +a
data_dir="${DATA_DIR:-./data}"
uploads_dir="${UPLOADS_DIR:-./uploads}"
mkdir -p "${data_dir}" "${uploads_dir}"
sudo chown -R 10001:10001 "${data_dir}" "${uploads_dir}"
docker compose config
docker compose pull
docker compose up -d
```

如果 GHCR 包是私有的，新服务器还需先使用具有最小 `read:packages` 权限的
GitHub PAT 登录；公开镜像可跳过：

```bash
read -rsp "GHCR PAT: " GHCR_TOKEN && echo
printf '%s' "${GHCR_TOKEN}" | \
  docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
unset GHCR_TOKEN
```

如需在本机验证 Dockerfile，可独立执行
`docker build --target runtime -t unrecycle-me:local .`。不要把本地临时构建的标签
写入生产 Compose，以免绕过 CI 烟测。

默认只绑定宿主回环地址。生产环境应由 Nginx 或 Caddy 提供 HTTPS 反向代理，并保持 `COOKIE_SECURE=true`。若不使用反向代理，需要自行调整 `BIND_ADDRESS`，同时配置 TLS 和防火墙，不能直接将无 TLS 的后台暴露到公网。

查看容器及健康状态：

```bash
docker compose ps
docker inspect unrecycle-me --format '{{json .State.Health}}'
docker compose logs --tail=200 web
```

容器健康检查每 30 秒请求一次 `/healthz`。该接口用于确认应用进程和数据库连接可用。更新时推荐先备份，再拉取镜像：

```bash
docker compose pull
docker compose up -d
docker image prune -f
```

需要稳定回滚时，将 `.env` 中的 `IMAGE_TAG` 设置为 CI 发布的 commit SHA，而不是继续使用 `latest`。

## 数据备份与恢复

数据库和上传图片都不在镜像内，分别持久化到 `DATA_DIR` 和 `UPLOADS_DIR`。仅有卷挂载不等于备份，建议定时复制到另一块磁盘或远程对象存储。

在线创建 SQLite 一致性备份：

```bash
set -a
source .env
set +a
mkdir -p backups
docker compose exec -T web python -c \
  "import sqlite3; s=sqlite3.connect('/app/data/blog.db'); d=sqlite3.connect('/app/data/.blog-backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp web:/app/data/.blog-backup.db "./backups/blog-$(date +%Y%m%d-%H%M%S).db"
docker compose exec -T web python -c \
  "from pathlib import Path; Path('/app/data/.blog-backup.db').unlink(missing_ok=True)"
tar -C "${UPLOADS_DIR:-./uploads}" -czf \
  "./backups/uploads-$(date +%Y%m%d-%H%M%S).tar.gz" .
```

恢复数据库前必须停止应用写入，并先保留当前数据库副本：

```bash
set -a
source .env
set +a
docker compose stop web
cp "${DATA_DIR:-./data}/blog.db" "./backups/blog-before-restore-$(date +%Y%m%d-%H%M%S).db"
cp ./backups/要恢复的备份.db "${DATA_DIR:-./data}/blog.db"
sudo chown 10001:10001 "${DATA_DIR:-./data}/blog.db"
docker compose up -d
docker compose ps
```

恢复上传文件时同样先停止应用，并保留当前目录：

```bash
set -a
source .env
set +a
docker compose stop web
uploads_dir="${UPLOADS_DIR:-./uploads}"
mv "${uploads_dir}" "${uploads_dir}.before-restore-$(date +%Y%m%d-%H%M%S)"
mkdir -p "${uploads_dir}"
tar -C "${uploads_dir}" -xzf ./backups/要恢复的上传备份.tar.gz
sudo chown -R 10001:10001 "${uploads_dir}"
docker compose up -d
```

恢复后检查首页、后台和上传图片，并执行 SQLite 完整性检查：

```bash
docker compose exec -T web python -c \
  "import sqlite3; c=sqlite3.connect('/app/data/blog.db'); print(c.execute('PRAGMA quick_check').fetchall()); c.close()"
```

## 密钥与密码轮换

- 修改 `SECRET_KEY` 会立即使已有 JWT 会话失效，所有管理员需要重新登录。
- 修改 `ADMIN_PASSWORD` 后需要重新创建容器，使进程读取新环境变量。
- 怀疑泄漏时应同时轮换两者，并检查管理内容、上传目录和访问日志。

```bash
# 更新 .env 后
docker compose up -d --force-recreate
docker compose ps
```

## CI/CD

`.github/workflows/deploy.yml` 的流程为：

1. 安装固定的生产与测试依赖。
2. 执行 Ruff 和 pytest（单次测试最长 60 秒）。
3. 构建一次非 root 运行镜像，使用临时持久化目录完成容器烟测。
4. 仅在 `main` push 时登录 GHCR，把通过烟测的同一镜像标记并发布为
   `latest` 和 commit SHA。

GitHub Actions 只负责测试和发布镜像，不会自动登录服务器部署。服务器仍需在本地验证满意并获得明确批准后，再手动执行更新命令。

## 运维注意事项

- 升级前同时备份 SQLite 和 uploads，并定期演练恢复。
- 使用 commit SHA 部署可避免 `latest` 漂移并方便回滚。
- 定期执行 `PRAGMA quick_check`，监控 `DATA_DIR` 和 `UPLOADS_DIR`；Compose 已将
  Docker `json-file` 日志限制为每个文件 10 MiB、最多 3 个文件。
- 不要把数据库、上传文件、`.env` 或本地虚拟环境打入镜像；`.dockerignore` 已为这些内容设置排除规则。
- 所有推送到远程仓库的变更，必须先由用户在本地手动验证并明确批准。
