from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.database import Base

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    category = Column(String(80), default="Tech", nullable=False)
    tags = Column(String(500), default="", nullable=False)  # Comma-separated tags
    is_published = Column(Boolean, default=True, nullable=False)
    views = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class NavLink(Base):
    __tablename__ = "nav_links"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    url = Column(String(2048), nullable=False)
    description = Column(String(1000), nullable=True)
    category = Column(String(80), default="General", nullable=False)
    icon = Column(String(200), nullable=True)  # Simple text icon or emoji
    order = Column(Integer, default=0, nullable=False)

class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    url = Column(String(2048), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(500), default="", nullable=False)  # Comma-separated tags
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(String(20), default="中等", nullable=False) # 简单, 中等, 困难
    secret_hash = Column(String(128), nullable=True) # 谜题答案 SHA-256 哈希值
    is_active = Column(Boolean, default=True, nullable=False)
    drop_enabled = Column(Boolean, default=False, nullable=False)
    code_stock = Column(Integer, default=0, nullable=False)
    drop_probability = Column(Float, default=0.2, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    codes = relationship("RedemptionCode", back_populates="game", cascade="all, delete-orphan")

class RedemptionCode(Base):
    __tablename__ = "redemption_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(200), unique=True, index=True, nullable=False)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="unused", nullable=False) # unused, used
    ip_address = Column(String(64), nullable=True)

    game = relationship("Game", back_populates="codes")
