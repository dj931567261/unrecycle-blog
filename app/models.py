from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from app.database import Base

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    category = Column(String, default="Tech")
    tags = Column(String, default="")  # Comma-separated tags
    is_published = Column(Boolean, default=True)
    views = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class NavLink(Base):
    __tablename__ = "nav_links"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    description = Column(String, nullable=True)
    category = Column(String, default="General")  # e.g., Dev, Design, Resources
    icon = Column(String, nullable=True)  # Simple text icon, emoji, or SVG path
    order = Column(Integer, default=0)

class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String, default="")  # Comma-separated tags
    created_at = Column(DateTime(timezone=True), server_default=func.now())
