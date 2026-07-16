import hashlib
import html
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit

import markdown
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from markdown.extensions import Extension
from markdown.extensions.sane_lists import SaneOListProcessor, SaneUListProcessor
from markdown.preprocessors import Preprocessor
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, crud, models, schemas
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    APP_ENV,
    COOKIE_NAME,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    ENABLE_DOCS,
    MAX_UPLOAD_BYTES,
    RUN_LEGACY_COMPAT_MIGRATION,
    SEED_INITIAL_DATA,
    STATIC_DIR,
    TEMPLATE_DIR,
    UPLOAD_CHUNK_SIZE,
    UPLOAD_DIR,
)
from app.database import Base, SessionLocal, engine, get_db


logger = logging.getLogger("unrecycle_me")
UPLOAD_PUBLIC_PREFIX = (
    "/static/uploads"
    if UPLOAD_DIR == (STATIC_DIR / "uploads").resolve()
    else "/uploads"
)


LEGACY_GAME_COLUMNS = {
    "drop_enabled": "ALTER TABLE games ADD COLUMN drop_enabled BOOLEAN NOT NULL DEFAULT 0",
    "code_stock": "ALTER TABLE games ADD COLUMN code_stock INTEGER NOT NULL DEFAULT 0",
    "drop_probability": "ALTER TABLE games ADD COLUMN drop_probability FLOAT NOT NULL DEFAULT 0.2",
}


def run_legacy_compatibility_migration() -> list[str]:
    """显式的一次性旧 games 表兼容迁移。

    默认启动不会执行 ALTER TABLE。需要兼容旧库时，先备份数据库，再单进程设置
    RUN_LEGACY_COMPAT_MIGRATION=true 启动一次，或直接调用本函数。
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Legacy compatibility migration currently supports SQLite only")

    inspector = inspect(engine)
    if not inspector.has_table("games"):
        return []

    migrated_columns: list[str] = []
    with engine.begin() as connection:
        existing_columns = {
            column["name"] for column in inspect(connection).get_columns("games")
        }
        for column_name, ddl in LEGACY_GAME_COLUMNS.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(ddl))
            existing_columns.add(column_name)
            migrated_columns.append(column_name)
    return migrated_columns


def seed_initial_data() -> None:
    """在单个事务中为全空业务表写入默认内容。

    SQLite 使用 BEGIN IMMEDIATE 串行化多个进程的首次初始化，避免 count/insert 竞态。
    已有任意数据的表不会被补种或覆盖。
    """
    db = SessionLocal()
    try:
        if engine.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            db.begin()

        if db.query(models.NavLink).count() == 0:
            db.add_all(
                [
                    models.NavLink(title="FastAPI 文档", url="https://fastapi.tiangolo.com", description="Python 现代 Web 框架官方中文文档", category="技术文档", icon="⚡", order=1),
                    models.NavLink(title="MDN Web", url="https://developer.mozilla.org/zh-CN", description="最权威的 Web 前端开发技术参考资料", category="技术文档", icon="📖", order=2),
                    models.NavLink(title="GitHub", url="https://github.com", description="全球开源代码托管与协作开发社区", category="常用网址", icon="🐙", order=1),
                    models.NavLink(title="Can I Use", url="https://caniuse.com", description="前端浏览器兼容性查询工具", category="常用网址", icon="🌐", order=2),
                ]
            )

        if db.query(models.Post).count() == 0:
            db.add(
                models.Post(
                    title="我的个人空间 Unrecycle-Me 正式发布！",
                    slug="unrecycle-me-released",
                    content="""欢迎来到我的个人数字花园！

这个系统是我专门设计用来管理我的**技术文章**、**网址导航**、**网站收藏**以及**日常小工具**的平台。

### 系统特色
- **极客暗黑风**：全局采用柔和的暗黑背景与毛玻璃（Glassmorphism）卡片设计，支持全响应式阅读。
- **即插即用的小工具箱**：内置开发者常用小工具（如本地 JSON 格式化），无后端接口请求，纯前端离线级处理。
- **极致的加载体验**：基于 FastAPI 服务端渲染与 SQLite，没有任何重量级前端依赖，静态页面秒开加载。

### 接下来计划
1. 在博客中整理我之前积累的一些开发调试笔记。
2. 收集更多我在工作和学习中沉淀的网址导航。
3. 扩展小工具箱：加入 Base64 转换和 URL 编解码等功能。

如果你对这个项目感兴趣，欢迎在管理后台中管理或修改内容！
""",
                    summary="这是我使用 FastAPI 和 SQLite 自主开发并搭建的个人主页与技术博客，集成了导航、书签和工具箱。",
                    category="日常记录",
                    tags="FastAPI,SQLite,Blog",
                    is_published=True,
                )
            )

        if db.query(models.Bookmark).count() == 0:
            db.add_all(
                [
                    models.Bookmark(title="Prism.js - 轻量级代码语法高亮工具", url="https://prismjs.com", description="一个非常小巧、速度极快的客户端代码高亮库，本站的技术文章代码块就是用它高亮渲染的。", tags="Frontend,Tools"),
                    models.Bookmark(title="FastAPI - Official Documentation", url="https://fastapi.tiangolo.com", description="FastAPI standard doc site", tags="Backend,Python"),
                ]
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    if RUN_LEGACY_COMPAT_MIGRATION:
        migrated = run_legacy_compatibility_migration()
        logger.info("Legacy compatibility migration completed: %s", migrated or "no changes")
    if SEED_INITIAL_DATA:
        seed_initial_data()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await run_in_threadpool(initialize_database)
    yield


app = FastAPI(
    title="Unrecycle-Me",
    description="Personal Developer Dashboard & Blog",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
    lifespan=lifespan,
)


def _same_origin(origin: str, request: Request) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    request_host = request.headers.get("host", "").lower()
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request_host


def _apply_security_headers(response, request: Request) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.bootcdn.net "
        "https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://cloudflareinsights.com",
    )
    if COOKIE_SECURE:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if request.url.path.startswith(
        ("/admin", "/login", "/api/auth", "/api/posts")
    ):
        response.headers["Cache-Control"] = "no-store"


@app.middleware("http")
async def security_and_timing_middleware(request: Request, call_next):
    started_at = time.perf_counter()

    # 无需改模板的基础 CSRF 防线：Cookie 鉴权的写请求拒绝明确的跨站来源。
    uses_cookie_auth = COOKIE_NAME in request.cookies and not request.headers.get("Authorization")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and uses_cookie_auth:
        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        origin = request.headers.get("Origin")
        if fetch_site == "cross-site" or (origin and not _same_origin(origin, request)):
            response = JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Cross-site request rejected"},
            )
            _apply_security_headers(response, request)
            return response

    try:
        response = await call_next(request)
    finally:
        duration = time.perf_counter() - started_at
        logger.info("Request %s %s completed in %.4fs", request.method, request.url.path, duration)

    _apply_security_headers(response, request)
    return response


@app.exception_handler(crud.DataConflictError)
async def data_conflict_handler(_request: Request, exc: crud.DataConflictError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


class CachedStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount(
    "/uploads",
    CachedStaticFiles(directory=str(UPLOAD_DIR), check_dir=False),
    name="uploads",
)

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _prefers_html_error_page(request: Request) -> bool:
    """仅为浏览器页面导航返回 HTML，避免 API 错误响应变成网页。"""
    if request.method not in {"GET", "HEAD"}:
        return False
    path = request.url.path
    if path == "/api" or path.startswith("/api/") or path == "/healthz":
        return False
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept or "application/xhtml+xml" in accept


def _add_vary_accept(response) -> None:
    vary_values = {
        value.strip().lower()
        for value in response.headers.get("Vary", "").split(",")
        if value.strip()
    }
    if "accept" not in vary_values:
        existing = response.headers.get("Vary")
        response.headers["Vary"] = f"{existing}, Accept" if existing else "Accept"


def _render_error_page(
    request: Request,
    status_code: int,
    *,
    is_admin: bool = False,
    reference: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
):
    error_content = {
        status.HTTP_404_NOT_FOUND: {
            "title": "页面没有找到",
            "heading": "这条路径没有留下内容。",
            "message": "它可能已经被移动、删除，或者地址中藏着一个小小的拼写错误。",
            "label": "NOT FOUND",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "title": "服务暂时不可用",
            "heading": "这里遇到了一点意外。",
            "message": "服务器未能完成这次请求。你可以稍后重试，已有文章和数据不会因此被清除。",
            "label": "INTERNAL ERROR",
        },
    }
    content = error_content.get(status_code, error_content[status.HTTP_500_INTERNAL_SERVER_ERROR])
    response = templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": status_code,
            "error_title": content["title"],
            "error_heading": content["heading"],
            "error_message": content["message"],
            "error_label": content["label"],
            "error_reference": reference,
            "requested_path": request.url.path,
            "is_admin": is_admin,
        },
        status_code=status_code,
        headers=headers,
    )
    response.headers["Cache-Control"] = "no-store"
    _add_vary_accept(response)
    _apply_security_headers(response, request)
    return response


@app.exception_handler(StarletteHTTPException)
async def browser_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code not in {
        status.HTTP_404_NOT_FOUND,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    } or not _prefers_html_error_page(request):
        response = await http_exception_handler(request, exc)
        if exc.status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        }:
            _add_vary_accept(response)
        return response

    return _render_error_page(
        request,
        exc.status_code,
        reference=uuid.uuid4().hex[:8].upper() if exc.status_code >= 500 else None,
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    reference = uuid.uuid4().hex[:8].upper()
    logger.error(
        "Unhandled exception [%s] during %s %s",
        reference,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if not _prefers_html_error_page(request):
        response = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "reference": reference},
        )
        response.headers["Cache-Control"] = "no-store"
        _add_vary_accept(response)
        _apply_security_headers(response, request)
        return response

    return _render_error_page(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        reference=reference,
    )


_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "img", "li", "ol", "p", "pre", "s", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_VOID_TAGS = {"br", "hr", "img"}
_BLOCKED_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "math", "template", "noscript"}
_GLOBAL_ATTRIBUTES = {"title"}
_TAG_ATTRIBUTES = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "code": {"class"},
    "div": {"class"},
    "h1": {"id"}, "h2": {"id"}, "h3": {"id"},
    "h4": {"id"}, "h5": {"id"}, "h6": {"id"},
    "ol": {"start"},
    "li": {"value"},
    "td": {"align"},
    "th": {"align"},
}
_SAFE_CLASS_RE = re.compile(r"^[a-zA-Z0-9_ -]{1,200}$")
_SAFE_ID_RE = re.compile(r"^[\w:.-]{1,200}$", re.UNICODE)


def _sanitize_content_url(value: str, *, image: bool = False) -> Optional[str]:
    decoded = html.unescape(value).strip()
    if not decoded or decoded.startswith(("//", "\\")):
        return None
    if any(ord(character) < 32 or character.isspace() for character in decoded):
        return None

    parsed = urlsplit(decoded)
    if parsed.scheme:
        allowed_schemes = {"http", "https"} if image else {"http", "https", "mailto"}
        if parsed.scheme.lower() not in allowed_schemes:
            return None
        if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
            return None
    return decoded


class MarkdownHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if self.blocked_depth:
            self.blocked_depth += 1
            return
        if tag in _BLOCKED_TAGS:
            self.blocked_depth = 1
            return
        if tag not in _ALLOWED_TAGS:
            return

        cleaned_attributes: list[tuple[str, str]] = []
        allowed_attributes = _GLOBAL_ATTRIBUTES | _TAG_ATTRIBUTES.get(tag, set())
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if raw_value is None or name.startswith("on"):
                continue

            if name == "style" and tag in {"td", "th"}:
                match = re.fullmatch(r"\s*text-align\s*:\s*(left|right|center)\s*;?\s*", raw_value, re.I)
                if match:
                    cleaned_attributes.append(("align", match.group(1).lower()))
                continue
            if name not in allowed_attributes:
                continue

            value = raw_value.strip()
            if name in {"href", "src"}:
                safe_url = _sanitize_content_url(value, image=name == "src")
                if safe_url is None:
                    continue
                value = safe_url
            elif name == "class":
                if not _SAFE_CLASS_RE.fullmatch(value):
                    continue
            elif name == "id":
                if not _SAFE_ID_RE.fullmatch(value):
                    continue
            elif name in {"width", "height", "start", "value"}:
                if not value.isdigit() or int(value) > 10_000:
                    continue
            elif name == "align":
                value = value.lower()
                if value not in {"left", "right", "center"}:
                    continue
            cleaned_attributes.append((name, value))

        if tag == "a":
            href = next((value for name, value in cleaned_attributes if name == "href"), None)
            if href and urlsplit(href).scheme in {"http", "https"}:
                cleaned_attributes.extend(
                    [("target", "_blank"), ("rel", "noopener noreferrer")]
                )

        attributes_text = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in cleaned_attributes
        )
        self.output.append(f"<{tag}{attributes_text}>")
        if tag not in _VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs):
        self.handle_starttag(tag, attrs)
        if self.blocked_depth:
            self.blocked_depth = max(0, self.blocked_depth - 1)
        elif self.open_tags and self.open_tags[-1] == tag.lower():
            self.open_tags.pop()
            self.output.append(f"</{tag.lower()}>")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self.blocked_depth:
            self.blocked_depth -= 1
            return
        if tag in _VOID_TAGS or not self.open_tags or self.open_tags[-1] != tag:
            return
        self.open_tags.pop()
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str):
        if not self.blocked_depth:
            self.output.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str):
        if not self.blocked_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str):
        if not self.blocked_depth:
            self.output.append(f"&#{name};")

    def get_html(self) -> str:
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output)


def sanitize_markdown_html(rendered_html: str) -> str:
    sanitizer = MarkdownHTMLSanitizer()
    sanitizer.feed(rendered_html)
    sanitizer.close()
    return sanitizer.get_html()


_MARKDOWN_LIST_ITEM_RE = re.compile(
    r"^(?P<indent> *)(?P<marker>[-*+]|\d+\.)(?P<spacing> +)(?P<content>.*)$"
)
_MARKDOWN_ORDERED_LIST_ITEM_RE = re.compile(r"^[ ]{0,3}\d+\.[ ]+")
_MARKDOWN_UNORDERED_LIST_ITEM_RE = re.compile(r"^[ ]{0,3}[-*+][ ]+")


def _markdown_list_content_indent(
    source_indent: int,
    marker: str,
    spacing: str,
) -> int:
    """计算 CommonMark 列表项正文起始列。"""
    padding = len(spacing) if len(spacing) <= 4 else 1
    return source_indent + len(marker) + padding


def _starts_new_markdown_block(stripped_line: str) -> bool:
    return stripped_line.startswith(("#", ">", "\x02"))


def _preprocess_markdown_lines(lines: list[str]) -> list[str]:
    """把 CommonMark 风格的嵌套列表缩进映射为 Python-Markdown 层级。

    此预处理器会在 fenced code 与原生 HTML 被 Markdown 暂存后运行，
    因此不会修改代码块中的 Markdown 示例。
    """
    new_lines: list[str] = []
    # 每层保存（原始 marker 缩进、该列表项正文的原始起始列）。
    active_list_levels: list[tuple[int, int]] = []
    saw_blank_line = False

    def append_blank_line() -> None:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")

    for index, line in enumerate(lines):
        if not line.strip():
            new_lines.append(line)
            saw_blank_line = True
            continue

        indent_match = _MARKDOWN_LIST_ITEM_RE.match(line)
        if indent_match:
            spaces = indent_match.group("indent")
            marker = indent_match.group("marker")
            post_spaces = indent_match.group("spacing")
            content = indent_match.group("content")
            source_indent = len(spaces)
            had_list_context = bool(active_list_levels)
            list_depth: Optional[int] = None

            for level_index in range(len(active_list_levels) - 1, -1, -1):
                if source_indent == active_list_levels[level_index][0]:
                    list_depth = level_index
                    break

            if list_depth is None:
                for level_index in range(len(active_list_levels) - 1, -1, -1):
                    child_indent = active_list_levels[level_index][1]
                    if child_indent <= source_indent <= child_indent + 3:
                        list_depth = level_index + 1
                        break

            if list_depth is None and source_indent <= 3:
                list_depth = 0

            if list_depth is not None:
                normalized_indent = source_indent if list_depth == 0 else list_depth * 4
                processed_line = (
                    " " * normalized_indent + marker + post_spaces + content
                )
                level = (
                    source_indent,
                    _markdown_list_content_indent(
                        source_indent,
                        marker,
                        post_spaces,
                    ),
                )
                active_list_levels[:] = active_list_levels[:list_depth]
                active_list_levels.append(level)

                if list_depth == 0 and not had_list_context and index > 0:
                    previous_line = lines[index - 1].strip()
                    if previous_line and not _MARKDOWN_LIST_ITEM_RE.match(
                        previous_line
                    ) and not previous_line.startswith(
                        ("#", ">", "`", "- ", "* ", "+ ")
                    ):
                        append_blank_line()

                new_lines.append(processed_line)
                saw_blank_line = False
                continue

        stripped_line = line.lstrip(" ")
        line_indent = len(line) - len(stripped_line)
        if active_list_levels and line_indent <= 3 and (
            saw_blank_line or _starts_new_markdown_block(stripped_line)
        ):
            active_list_levels.clear()

        new_lines.append(line)
        saw_blank_line = False

    return new_lines


class _MarkdownListPreprocessor(Preprocessor):
    def run(self, lines: list[str]) -> list[str]:
        return _preprocess_markdown_lines(lines)


def _markdown_list_kind(line: str) -> Optional[str]:
    if _MARKDOWN_ORDERED_LIST_ITEM_RE.match(line):
        return "ordered"
    if _MARKDOWN_UNORDERED_LIST_ITEM_RE.match(line):
        return "unordered"
    return None


def _split_mixed_list_block(blocks: list[str]) -> None:
    """一次扫描拆分同层级列表类型，避免交替列表出现二次复杂度。"""
    lines = blocks[0].split("\n")
    current_kind = _markdown_list_kind(lines[0])
    segments: list[str] = []
    segment_start = 0
    for index, line in enumerate(lines[1:], start=1):
        line_kind = _markdown_list_kind(line)
        if line_kind is None or line_kind == current_kind:
            continue
        segments.append("\n".join(lines[segment_start:index]))
        segment_start = index
        current_kind = line_kind
    if segments:
        segments.append("\n".join(lines[segment_start:]))
        blocks[0:1] = segments


class _OrderedListProcessor(SaneOListProcessor):
    def run(self, parent, blocks: list[str]):
        _split_mixed_list_block(blocks)
        return super().run(parent, blocks)


class _UnorderedListProcessor(SaneUListProcessor):
    def run(self, parent, blocks: list[str]):
        _split_mixed_list_block(blocks)
        return super().run(parent, blocks)


class _BlogMarkdownExtension(Extension):
    def extendMarkdown(self, md):
        # fenced_code(25) 和 html_block(20) 会先暂存代码及原生 HTML；
        # 列表预处理放在其后，避免改写代码示例中的列表标记。
        md.preprocessors.register(
            _MarkdownListPreprocessor(md),
            "blog_mixed_lists",
            15,
        )
        md.parser.blockprocessors.register(
            _OrderedListProcessor(md.parser),
            "olist",
            40,
        )
        md.parser.blockprocessors.register(
            _UnorderedListProcessor(md.parser),
            "ulist",
            30,
        )


def render_markdown(value: str) -> str:
    if not value:
        return ""

    rendered = markdown.markdown(
        value,
        extensions=["fenced_code", "tables", "toc", "nl2br", _BlogMarkdownExtension()],
    )
    return sanitize_markdown_html(rendered)


templates.env.filters["markdown"] = render_markdown


def format_datetime(value, date_format: str = "%Y-%m-%d"):
    if not value:
        return ""
    if isinstance(value, str):
        for known_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, known_format).strftime(date_format)
            except ValueError:
                continue
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return value[:10]
        return value
    try:
        return value.strftime(date_format)
    except AttributeError:
        return str(value)


templates.env.filters["datetime"] = format_datetime


def _pagination(page: int, page_size: int, total: int) -> dict:
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, math.ceil(total / page_size)),
    }


def _clamp_page(page: int, page_size: int, total: int) -> int:
    """将用户传入的页码限制在当前有效范围内。"""
    return min(page, max(1, math.ceil(total / page_size)))


@app.get("/healthz", include_in_schema=False)
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "environment": APP_ENV}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(12, ge=1, le=30),
    db: Session = Depends(get_db),
):
    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="Search query must not be empty")

    pattern = f"%{_escape_like(keyword)}%"
    results: list[dict] = []

    posts = (
        db.query(models.Post)
        .filter(
            models.Post.is_published.is_(True),
            or_(
                models.Post.title.ilike(pattern, escape="\\"),
                models.Post.summary.ilike(pattern, escape="\\"),
                models.Post.category.ilike(pattern, escape="\\"),
                models.Post.tags.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(models.Post.created_at.desc(), models.Post.id.desc())
        .limit(limit)
        .all()
    )
    results.extend(
        {
            "type": "post",
            "title": post.title,
            "url": f"/blog/{post.slug}",
            "description": post.summary or post.category,
            "icon": "📄",
        }
        for post in posts
    )

    if len(results) < limit:
        nav_limit = limit - len(results)
        nav_links = (
            db.query(models.NavLink)
            .filter(
                or_(
                    models.NavLink.title.ilike(pattern, escape="\\"),
                    models.NavLink.description.ilike(pattern, escape="\\"),
                    models.NavLink.category.ilike(pattern, escape="\\"),
                )
            )
            .order_by(models.NavLink.order.asc(), models.NavLink.title.asc())
            .limit(nav_limit)
            .all()
        )
        results.extend(
            {
                "type": "nav",
                "title": link.title,
                "url": link.url,
                "description": link.description or link.category,
                "icon": link.icon or "🧭",
            }
            for link in nav_links
        )

    if len(results) < limit:
        bookmark_limit = limit - len(results)
        bookmarks = (
            db.query(models.Bookmark)
            .filter(
                or_(
                    models.Bookmark.title.ilike(pattern, escape="\\"),
                    models.Bookmark.description.ilike(pattern, escape="\\"),
                    models.Bookmark.tags.ilike(pattern, escape="\\"),
                )
            )
            .order_by(models.Bookmark.created_at.desc(), models.Bookmark.id.desc())
            .limit(bookmark_limit)
            .all()
        )
        results.extend(
            {
                "type": "bookmark",
                "title": bookmark.title,
                "url": bookmark.url,
                "description": bookmark.description or bookmark.tags,
                "icon": "🔖",
            }
            for bookmark in bookmarks
        )

    return {"query": keyword, "results": results, "count": len(results)}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    nav_links = crud.get_nav_links(db)
    recent_posts = crud.get_posts(db, limit=5, published_only=True)
    bookmarks = crud.get_bookmarks(db, limit=6)
    categorized_links = {}
    for link in nav_links:
        categorized_links.setdefault(link.category, []).append(link)
    return templates.TemplateResponse(request, "index.html", {
        "categorized_links": categorized_links,
        "recent_posts": recent_posts,
        "bookmarks": bookmarks,
        "is_admin": current_user is not None,
    })


@app.get("/blog", response_class=HTMLResponse)
def blog_list(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[str] = Depends(auth.get_current_user_optional),
):
    published_only = current_user is None
    total = crud.count_posts(db, published_only=published_only)
    page = _clamp_page(page, page_size, total)
    posts = crud.get_posts(db, skip=(page - 1) * page_size, limit=page_size, published_only=published_only)
    return templates.TemplateResponse(request, "blog_list.html", {
        "posts": posts,
        "is_admin": current_user is not None,
        "pagination": _pagination(page, page_size, total),
    })


@app.get("/blog/{slug}", response_class=HTMLResponse)
def blog_detail(request: Request, slug: str, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    post = crud.get_post_by_slug(db, slug)
    if not post or (current_user is None and post.is_published is not True):
        raise HTTPException(status_code=404, detail="Article not found")
    if current_user is None:
        post = crud.increment_post_views(db, post.id)
    return templates.TemplateResponse(request, "blog_detail.html", {
        "post": post,
        "is_admin": current_user is not None,
    })


@app.get("/bookmarks", response_class=HTMLResponse)
def bookmarks_list(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tag: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    current_user: Optional[str] = Depends(auth.get_current_user_optional),
):
    tags = crud.get_all_bookmark_tags(db)
    requested_tag = tag.strip() if tag else None
    selected_tag = next(
        (existing_tag for existing_tag in tags if existing_tag.casefold() == requested_tag.casefold()),
        requested_tag,
    ) if requested_tag else None
    bookmarks, total, page = crud.get_bookmarks_page(
        db,
        page=page,
        page_size=page_size,
        tag=selected_tag,
    )
    return templates.TemplateResponse(request, "bookmarks.html", {
        "bookmarks": bookmarks,
        "is_admin": current_user is not None,
        "tags": tags,
        "selected_tag": selected_tag,
        "pagination": _pagination(page, page_size, total),
    })


@app.get("/tools", response_class=HTMLResponse)
async def tools_list_page(request: Request, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    return templates.TemplateResponse(request, "tools_list.html", {"is_admin": current_user is not None})


@app.get("/tools/{tool_name}", response_class=HTMLResponse)
async def render_tool(request: Request, tool_name: str, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    if not re.fullmatch(r"[a-z0-9-]{1,64}", tool_name):
        raise HTTPException(status_code=404, detail="Tool not found")
    template_file = f"tools/{tool_name.replace('-', '_')}.html"
    try:
        templates.get_template(template_file)
    except TemplateNotFound:
        raise HTTPException(status_code=404, detail="Tool not found")
    return templates.TemplateResponse(request, template_file, {"is_admin": current_user is not None})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    if current_user:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


def _model_to_dict(obj):
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        result[column.name] = value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value
    return result


def _serialize_post_summary(post: dict) -> dict:
    """将后台文章元数据转换为可安全写入模板的字典。"""
    return {
        key: value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, datetime)
        else value
        for key, value in post.items()
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    post_page: int = Query(1, ge=1),
    bookmark_page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[str] = Depends(auth.get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    try:
        post_total = crud.count_posts(db, published_only=False)
        bookmark_total = crud.count_bookmarks(db)
        post_page = _clamp_page(post_page, page_size, post_total)
        bookmark_page = _clamp_page(bookmark_page, page_size, bookmark_total)
        posts = crud.get_post_admin_summaries(
            db,
            skip=(post_page - 1) * page_size,
            limit=page_size,
        )
        nav_links = crud.get_nav_links(db)
        bookmarks = crud.get_bookmarks(db, skip=(bookmark_page - 1) * page_size, limit=page_size)

        default_categories = ["常用网址", "技术文档", "开发工具", "设计资源"]
        nav_categories = sorted(set(default_categories + [link.category for link in nav_links if link.category]))
        bookmark_tags = crud.get_all_bookmark_tags(db)
        return templates.TemplateResponse(request, "admin.html", {
            "posts": [_serialize_post_summary(post) for post in posts],
            "nav_links": [_model_to_dict(link) for link in nav_links],
            "bookmarks": [_model_to_dict(bookmark) for bookmark in bookmarks],
            "redemption_codes": [],
            "games": [],
            "username": current_user,
            "nav_categories": nav_categories,
            "bookmark_tags": bookmark_tags,
            "post_pagination": _pagination(post_page, page_size, post_total),
            "bookmark_pagination": _pagination(bookmark_page, page_size, bookmark_total),
        })
    except Exception as exc:
        reference = uuid.uuid4().hex[:8].upper()
        logger.error(
            "Failed to render admin page [%s]",
            reference,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _render_error_page(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            is_admin=True,
            reference=reference,
        )


def _post_editor_context(
    db: Session,
    *,
    username: str,
    post_id: Optional[int],
) -> dict:
    post_categories, post_tags = crud.get_post_editor_options(db)
    return {
        "username": username,
        "is_admin": True,
        "is_new": post_id is None,
        "post_id": post_id,
        "post_categories": post_categories,
        "post_tags": post_tags,
    }


@app.get("/admin/posts/new", response_class=HTMLResponse)
def new_post_editor_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[str] = Depends(auth.get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "post_editor.html",
        _post_editor_context(db, username=current_user, post_id=None),
    )


@app.get("/admin/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_editor_page(
    request: Request,
    post_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[str] = Depends(auth.get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=303,
        )
    if not crud.post_exists(db, post_id):
        raise HTTPException(status_code=404, detail="Post not found")
    return templates.TemplateResponse(
        request,
        "post_editor.html",
        _post_editor_context(db, username=current_user, post_id=post_id),
    )


@app.post("/api/auth/login")
async def api_login(request: Request, form_data: schemas.UserLogin):
    rate_limit_key = auth.build_login_rate_limit_key(request, form_data.username)
    retry_after = auth.get_login_retry_after(rate_limit_key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    credentials_valid = await run_in_threadpool(
        auth.verify_admin_credentials,
        form_data.username,
        form_data.password,
    )
    if not credentials_valid:
        auth.record_login_failure(rate_limit_key)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    auth.clear_login_failures(rate_limit_key)
    access_token = auth.create_access_token({"sub": form_data.username})
    response = JSONResponse(content={"message": "Login successful"})
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    token = auth.get_request_token(request)
    if token:
        auth.revoke_access_token(token)
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite=COOKIE_SAMESITE,
    )
    return response


_POST_REVISION_FIELDS = (
    "title",
    "slug",
    "content",
    "summary",
    "category",
    "tags",
    "is_published",
)
_POST_REVISION_HEADER = "X-Post-Revision"
_POST_CONFLICT_DETAIL = (
    "Post was modified in another session. Reload the latest version before saving."
)


def _post_revision(post) -> str:
    """基于全部可编辑字段生成不受代理压缩影响的应用版本号。"""
    canonical = json.dumps(
        {field: getattr(post, field) for field in _POST_REVISION_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _post_version_headers(post) -> dict[str, str]:
    revision = _post_revision(post)
    return {
        "ETag": f'"{revision}"',
        _POST_REVISION_HEADER: revision,
    }


def _normalize_etag_candidate(candidate: str) -> str:
    """兼容 Nginx gzip 将源站强 ETag 自动弱化为 W/ 的情况。"""
    normalized = candidate.strip()
    if normalized[:2].upper() == "W/":
        normalized = normalized[2:].lstrip()
    return normalized


def _if_match_satisfied(if_match: str, current_etag: str) -> bool:
    """校验 If-Match，并兼容代理对应用内容哈希添加的弱标签前缀。"""
    candidates = {
        _normalize_etag_candidate(candidate)
        for candidate in if_match.split(",")
    }
    return "*" in candidates or current_etag in candidates


def _post_revision_matches_request(request: Request, current_revision: str) -> bool:
    provided_revision = request.headers.get(_POST_REVISION_HEADER)
    if provided_revision is not None:
        return provided_revision.strip() == current_revision

    if_match = request.headers.get("if-match")
    if if_match is None:
        return True
    return _if_match_satisfied(if_match, f'"{current_revision}"')


@app.post("/api/posts", response_model=schemas.PostInDB, status_code=status.HTTP_201_CREATED)
def create_post(
    post: schemas.PostCreate,
    response: Response,
    db: Session = Depends(get_db),
    _current_user: str = Depends(auth.get_current_user),
):
    if crud.get_post_by_slug(db, post.slug):
        raise HTTPException(status_code=409, detail="Slug already exists")
    created = crud.create_post(db, post)
    response.headers.update(_post_version_headers(created))
    return created


@app.get("/api/posts/{post_id}", response_model=schemas.PostInDB)
def api_get_post(
    post_id: int,
    response: Response,
    db: Session = Depends(get_db),
    _current_user: str = Depends(auth.get_current_user),
):
    post = crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    response.headers.update(_post_version_headers(post))
    return post


@app.put("/api/posts/{post_id}", response_model=schemas.PostInDB)
def update_post(
    post_id: int,
    post_update: schemas.PostUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _current_user: str = Depends(auth.get_current_user),
):
    # SQLite 需要在读取当前版本前锁定写事务，避免两个并发
    # If-Match 请求同时通过检查后互相覆盖。
    if engine.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    current = (
        db.query(models.Post)
        .filter(models.Post.id == post_id)
        .with_for_update()
        .first()
    )
    if not current:
        raise HTTPException(status_code=404, detail="Post not found")

    current_revision = _post_revision(current)
    if not _post_revision_matches_request(request, current_revision):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_POST_CONFLICT_DETAIL,
            headers={
                "ETag": f'"{current_revision}"',
                _POST_REVISION_HEADER: current_revision,
            },
        )

    if post_update.slug:
        existing = crud.get_post_by_slug(db, post_update.slug)
        if existing and existing.id != post_id:
            raise HTTPException(status_code=409, detail="Slug already exists")
    updated = crud.update_post(db, post_id, post_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Post not found")
    response.headers.update(_post_version_headers(updated))
    return updated


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    if not crud.delete_post(db, post_id):
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Post deleted successfully"}


@app.post("/api/nav_links", response_model=schemas.NavLinkInDB, status_code=status.HTTP_201_CREATED)
def create_nav_link(nav_link: schemas.NavLinkCreate, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    return crud.create_nav_link(db, nav_link)


@app.put("/api/nav_links/{link_id}", response_model=schemas.NavLinkInDB)
def update_nav_link(link_id: int, link_update: schemas.NavLinkUpdate, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    updated = crud.update_nav_link(db, link_id, link_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Navigation link not found")
    return updated


@app.delete("/api/nav_links/{link_id}")
def delete_nav_link(link_id: int, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    if not crud.delete_nav_link(db, link_id):
        raise HTTPException(status_code=404, detail="Navigation link not found")
    return {"message": "Navigation link deleted successfully"}


@app.post("/api/bookmarks", response_model=schemas.BookmarkInDB, status_code=status.HTTP_201_CREATED)
def create_bookmark(bookmark: schemas.BookmarkCreate, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    return crud.create_bookmark(db, bookmark)


@app.put("/api/bookmarks/{bookmark_id}", response_model=schemas.BookmarkInDB)
def update_bookmark(bookmark_id: int, bookmark_update: schemas.BookmarkUpdate, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    updated = crud.update_bookmark(db, bookmark_id, bookmark_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return updated


@app.delete("/api/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: int, db: Session = Depends(get_db), _current_user: str = Depends(auth.get_current_user)):
    if not crud.delete_bookmark(db, bookmark_id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"message": "Bookmark deleted successfully"}


class UploadRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_UPLOAD_TYPES = {
    ".jpg": {"mime": {"image/jpeg"}, "kind": "jpeg", "suffix": ".jpg"},
    ".jpeg": {"mime": {"image/jpeg"}, "kind": "jpeg", "suffix": ".jpg"},
    ".png": {"mime": {"image/png"}, "kind": "png", "suffix": ".png"},
    ".gif": {"mime": {"image/gif"}, "kind": "gif", "suffix": ".gif"},
    ".webp": {"mime": {"image/webp"}, "kind": "webp", "suffix": ".webp"},
}


def _matches_image_magic(data: bytes, kind: str) -> bool:
    if kind == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if kind == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if kind == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _save_upload(source, destination: Path, expected_kind: str) -> int:
    temporary_path: Optional[Path] = None
    total_bytes = 0
    first_chunk = True
    try:
        source.seek(0)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=UPLOAD_DIR,
            prefix=".upload-",
            suffix=".part",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            while True:
                chunk = source.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                if first_chunk:
                    first_chunk = False
                    if not _matches_image_magic(chunk, expected_kind):
                        raise UploadRejected(400, "File content does not match the declared image format")
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise UploadRejected(413, f"File exceeds the {MAX_UPLOAD_BYTES}-byte upload limit")
                temporary_file.write(chunk)

        if first_chunk:
            raise UploadRejected(400, "Empty files are not allowed")
        os.replace(temporary_path, destination)
        temporary_path = None
        return total_bytes
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@app.post("/api/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...), _current_user: str = Depends(auth.get_current_user)):
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()
    upload_type = _UPLOAD_TYPES.get(extension)
    if not upload_type:
        raise HTTPException(status_code=400, detail="Unsupported file format")
    if (file.content_type or "").lower() not in upload_type["mime"]:
        raise HTTPException(status_code=400, detail="MIME type does not match the file extension")

    filename = f"{uuid.uuid4().hex}{upload_type['suffix']}"
    destination = UPLOAD_DIR / filename
    try:
        size = await run_in_threadpool(
            _save_upload,
            file.file,
            destination,
            upload_type["kind"],
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except OSError:
        logger.exception("Failed to persist uploaded image")
        raise HTTPException(status_code=500, detail="Failed to save file")
    finally:
        await file.close()

    return {"url": f"{UPLOAD_PUBLIC_PREFIX}/{filename}", "size": size}
