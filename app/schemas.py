import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


SLUG_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]+(?:-[\w\u4e00-\u9fff]+)*$", re.UNICODE)


def _non_empty_text(value: str, field_name: str, *, strip: bool = True) -> str:
    candidate = value.strip() if strip else value
    if not candidate.strip():
        raise ValueError(f"{field_name} must not be empty")
    return candidate


def _validate_slug(value: str) -> str:
    slug = _non_empty_text(value, "slug").lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("slug may only contain letters, numbers, underscores, Chinese characters and hyphens")
    return slug


def _validate_http_url(value: str) -> str:
    url = _non_empty_text(value, "url")
    if any(ord(character) < 32 for character in url):
        raise ValueError("url must not contain control characters")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("url is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must use the http or https protocol")
    if parsed.username or parsed.password:
        raise ValueError("url must not contain embedded credentials")
    return url


def _normalize_tags(value: str) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in value.split(","):
        tag = raw_tag.strip()
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    normalized = ",".join(tags)
    if len(normalized) > 500:
        raise ValueError("tags must not exceed 500 characters")
    return normalized


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)
    summary: Optional[str] = Field(default=None, max_length=2_000)
    category: str = Field(default="Tech", min_length=1, max_length=80)
    tags: str = Field(default="", max_length=500)
    is_published: bool = True

    @field_validator("title", "category")
    @classmethod
    def validate_required_text(cls, value: str, info):
        return _non_empty_text(value, info.field_name)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str):
        return _validate_slug(value)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str):
        return _non_empty_text(value, "content", strip=False)

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: str):
        return _normalize_tags(value)


class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, min_length=1, max_length=2_000_000)
    summary: Optional[str] = Field(default=None, max_length=2_000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    tags: Optional[str] = Field(default=None, max_length=500)
    is_published: Optional[bool] = None

    @field_validator("title", "slug", "content", "category", "tags", "is_published", mode="before")
    @classmethod
    def reject_explicit_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} must not be null")
        return value

    @field_validator("title", "category")
    @classmethod
    def validate_required_text(cls, value: Optional[str], info):
        return _non_empty_text(value, info.field_name) if value is not None else value

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: Optional[str]):
        return _validate_slug(value) if value is not None else value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: Optional[str]):
        return _non_empty_text(value, "content", strip=False) if value is not None else value

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: Optional[str]):
        return _normalize_tags(value) if value is not None else value


class PostInDB(PostBase):
    id: int
    views: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NavLinkBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    description: Optional[str] = Field(default=None, max_length=1_000)
    category: str = Field(default="General", min_length=1, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=200)
    order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("title", "category")
    @classmethod
    def validate_required_text(cls, value: str, info):
        return _non_empty_text(value, info.field_name)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str):
        return _validate_http_url(value)

    @field_validator("description", "icon")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class NavLinkCreate(NavLinkBase):
    pass


class NavLinkUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    description: Optional[str] = Field(default=None, max_length=1_000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=200)
    order: Optional[int] = Field(default=None, ge=-100_000, le=100_000)

    @field_validator("title", "url", "category", "order", mode="before")
    @classmethod
    def reject_explicit_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} must not be null")
        return value

    @field_validator("title", "category")
    @classmethod
    def validate_required_text(cls, value: Optional[str], info):
        return _non_empty_text(value, info.field_name) if value is not None else value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: Optional[str]):
        return _validate_http_url(value) if value is not None else value

    @field_validator("description", "icon")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class NavLinkInDB(NavLinkBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class BookmarkBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    description: Optional[str] = Field(default=None, max_length=5_000)
    tags: str = Field(default="", max_length=500)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str):
        return _non_empty_text(value, "title")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str):
        return _validate_http_url(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: str):
        return _normalize_tags(value)


class BookmarkCreate(BookmarkBase):
    pass


class BookmarkUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    description: Optional[str] = Field(default=None, max_length=5_000)
    tags: Optional[str] = Field(default=None, max_length=500)

    @field_validator("title", "url", "tags", mode="before")
    @classmethod
    def reject_explicit_null(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} must not be null")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: Optional[str]):
        return _non_empty_text(value, "title") if value is not None else value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: Optional[str]):
        return _validate_http_url(value) if value is not None else value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: Optional[str]):
        return _normalize_tags(value) if value is not None else value


class BookmarkInDB(BookmarkBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str):
        return _non_empty_text(value, "username")

    @field_validator("password")
    @classmethod
    def validate_bcrypt_length(cls, value: str):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 UTF-8 bytes")
        return value


class TokenData(BaseModel):
    username: Optional[str] = None


# 以下游戏 Schema 仅为旧数据库兼容保留，当前应用没有公开游戏路由。
class GameBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5_000)
    difficulty: str = Field(default="中等", min_length=1, max_length=20)
    is_active: bool = True
    drop_enabled: bool = False
    code_stock: int = Field(default=0, ge=0)
    drop_probability: float = Field(default=0.2, ge=0, le=1)

    @field_validator("title", "difficulty")
    @classmethod
    def validate_required_text(cls, value: str, info):
        return _non_empty_text(value, info.field_name)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str):
        return _validate_slug(value)


class GameCreate(GameBase):
    secret_hash: Optional[str] = Field(default=None, max_length=128)


class GameUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5_000)
    difficulty: Optional[str] = Field(default=None, min_length=1, max_length=20)
    secret_hash: Optional[str] = Field(default=None, max_length=128)
    is_active: Optional[bool] = None
    drop_enabled: Optional[bool] = None
    code_stock: Optional[int] = Field(default=None, ge=0)
    drop_probability: Optional[float] = Field(default=None, ge=0, le=1)


class GameInDB(GameBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RedemptionCodeBase(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    game_id: int = Field(gt=0)
    status: str = Field(default="unused", pattern=r"^(unused|used)$")
    ip_address: Optional[str] = Field(default=None, max_length=64)


class RedemptionCodeCreate(RedemptionCodeBase):
    pass


class RedemptionCodeInDB(RedemptionCodeBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
