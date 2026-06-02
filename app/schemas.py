from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# Post Schemas
class PostBase(BaseModel):
    title: str
    slug: str
    content: str
    summary: Optional[str] = None
    category: Optional[str] = "Tech"
    tags: Optional[str] = ""
    is_published: Optional[bool] = True

class PostCreate(PostBase):
    pass

class PostUpdate(PostBase):
    title: Optional[str] = None
    slug: Optional[str] = None
    content: Optional[str] = None
    is_published: Optional[bool] = None

class PostInDB(PostBase):
    id: int
    views: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# NavLink Schemas
class NavLinkBase(BaseModel):
    title: str
    url: str
    description: Optional[str] = None
    category: Optional[str] = "General"
    icon: Optional[str] = None
    order: Optional[int] = 0

class NavLinkCreate(NavLinkBase):
    pass

class NavLinkUpdate(NavLinkBase):
    title: Optional[str] = None
    url: Optional[str] = None

class NavLinkInDB(NavLinkBase):
    id: int

    class Config:
        from_attributes = True

# Bookmark Schemas
class BookmarkBase(BaseModel):
    title: str
    url: str
    description: Optional[str] = None
    tags: Optional[str] = ""

class BookmarkCreate(BookmarkBase):
    pass

class BookmarkInDB(BookmarkBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Authentication Schemas
class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
