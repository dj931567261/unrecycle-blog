from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func, ForeignKey, Float
from sqlalchemy.orm import relationship
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

class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(String, default="中等") # 简单, 中等, 困难
    secret_hash = Column(String, nullable=True) # 谜题答案 SHA-256 哈希值
    is_active = Column(Boolean, default=True)
    drop_enabled = Column(Boolean, default=False)
    code_stock = Column(Integer, default=0)
    drop_probability = Column(Float, default=0.2)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    codes = relationship("RedemptionCode", back_populates="game", cascade="all, delete-orphan")

class RedemptionCode(Base):
    __tablename__ = "redemption_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="unused") # unused, used
    ip_address = Column(String, nullable=True)

    game = relationship("Game", back_populates="codes")

