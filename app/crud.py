from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas


class DataConflictError(Exception):
    """数据库唯一约束或其他完整性约束冲突。"""


def _commit(db: Session, conflict_message: str = "Data conflict") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DataConflictError(conflict_message) from exc
    except Exception:
        db.rollback()
        raise


def get_post(db: Session, post_id: int):
    return db.query(models.Post).filter(models.Post.id == post_id).first()


def get_post_by_slug(db: Session, slug: str):
    return db.query(models.Post).filter(models.Post.slug == slug).first()


def get_posts(db: Session, skip: int = 0, limit: int = 100, published_only: bool = True):
    query = db.query(models.Post)
    if published_only:
        query = query.filter(models.Post.is_published.is_(True))
    return query.order_by(models.Post.created_at.desc(), models.Post.id.desc()).offset(skip).limit(limit).all()


def count_posts(db: Session, published_only: bool = True) -> int:
    query = db.query(func.count(models.Post.id))
    if published_only:
        query = query.filter(models.Post.is_published.is_(True))
    return int(query.scalar() or 0)


def create_post(db: Session, post: schemas.PostCreate):
    db_post = models.Post(**post.model_dump())
    db.add(db_post)
    _commit(db, "Slug already exists")
    db.refresh(db_post)
    return db_post


def update_post(db: Session, post_id: int, post_update: schemas.PostUpdate):
    db_post = get_post(db, post_id)
    if not db_post:
        return None

    for key, value in post_update.model_dump(exclude_unset=True).items():
        setattr(db_post, key, value)

    _commit(db, "Slug already exists")
    db.refresh(db_post)
    return db_post


def delete_post(db: Session, post_id: int):
    db_post = get_post(db, post_id)
    if not db_post:
        return False
    db.delete(db_post)
    _commit(db)
    return True


def increment_post_views(db: Session, post_id: int):
    statement = (
        update(models.Post)
        .where(models.Post.id == post_id)
        .values(views=func.coalesce(models.Post.views, 0) + 1)
    )
    result = db.execute(statement)
    if result.rowcount:
        _commit(db)
    else:
        db.rollback()
    return get_post(db, post_id)


def get_nav_links(db: Session):
    return db.query(models.NavLink).order_by(models.NavLink.order.asc(), models.NavLink.title.asc()).all()


def create_nav_link(db: Session, nav_link: schemas.NavLinkCreate):
    db_link = models.NavLink(**nav_link.model_dump())
    db.add(db_link)
    _commit(db)
    db.refresh(db_link)
    return db_link


def update_nav_link(db: Session, link_id: int, link_update: schemas.NavLinkUpdate):
    db_link = db.query(models.NavLink).filter(models.NavLink.id == link_id).first()
    if not db_link:
        return None

    for key, value in link_update.model_dump(exclude_unset=True).items():
        setattr(db_link, key, value)

    _commit(db)
    db.refresh(db_link)
    return db_link


def delete_nav_link(db: Session, link_id: int):
    db_link = db.query(models.NavLink).filter(models.NavLink.id == link_id).first()
    if not db_link:
        return False
    db.delete(db_link)
    _commit(db)
    return True


def _bookmark_has_tag(raw_tags: str | None, tag: str) -> bool:
    selected_key = tag.strip().casefold()
    return bool(selected_key) and any(
        raw_tag.strip().casefold() == selected_key
        for raw_tag in (raw_tags or "").split(",")
    )


def get_bookmarks(db: Session, skip: int = 0, limit: int = 100, tag: str | None = None):
    query = db.query(models.Bookmark).order_by(
        models.Bookmark.created_at.desc(),
        models.Bookmark.id.desc(),
    )
    if not tag:
        return query.offset(skip).limit(limit).all()

    # 标签目前以兼容旧数据的 CSV 保存。使用 Python casefold 精确比较每个 token，
    # 可正确区分内部空格，并覆盖 SQLite lower() 无法处理的 Unicode 大小写。
    matches = [bookmark for bookmark in query.all() if _bookmark_has_tag(bookmark.tags, tag)]
    return matches[skip:skip + limit]


def count_bookmarks(db: Session, tag: str | None = None) -> int:
    if not tag:
        return int(db.query(func.count(models.Bookmark.id)).scalar() or 0)
    values = db.query(models.Bookmark.tags).all()
    return sum(_bookmark_has_tag(raw_tags, tag) for (raw_tags,) in values)


def get_bookmarks_page(
    db: Session,
    page: int,
    page_size: int,
    tag: str | None = None,
) -> tuple[list[models.Bookmark], int, int]:
    """一次生成收藏筛选页，避免 CSV 标签模式下为 count/items 重复扫描。"""
    if not tag:
        total = count_bookmarks(db)
        bounded_page = min(page, max(1, (total + page_size - 1) // page_size))
        items = get_bookmarks(
            db,
            skip=(bounded_page - 1) * page_size,
            limit=page_size,
        )
        return items, total, bounded_page

    query = db.query(models.Bookmark).order_by(
        models.Bookmark.created_at.desc(),
        models.Bookmark.id.desc(),
    )
    matches = [bookmark for bookmark in query.all() if _bookmark_has_tag(bookmark.tags, tag)]
    total = len(matches)
    bounded_page = min(page, max(1, (total + page_size - 1) // page_size))
    start = (bounded_page - 1) * page_size
    return matches[start:start + page_size], total, bounded_page


def get_all_bookmark_tags(db: Session) -> list[str]:
    values = (
        db.query(models.Bookmark.tags)
        .filter(models.Bookmark.tags != "")
        .order_by(models.Bookmark.id.asc())
        .all()
    )
    unique_tags: dict[str, str] = {}
    for (raw_tags,) in values:
        for raw_tag in (raw_tags or "").split(","):
            tag = raw_tag.strip()
            if tag:
                unique_tags.setdefault(tag.casefold(), tag)
    return sorted(unique_tags.values(), key=str.casefold)


def create_bookmark(db: Session, bookmark: schemas.BookmarkCreate):
    db_bookmark = models.Bookmark(**bookmark.model_dump())
    db.add(db_bookmark)
    _commit(db)
    db.refresh(db_bookmark)
    return db_bookmark


def update_bookmark(db: Session, bookmark_id: int, bookmark_update: schemas.BookmarkUpdate):
    db_bookmark = db.query(models.Bookmark).filter(models.Bookmark.id == bookmark_id).first()
    if not db_bookmark:
        return None
    for key, value in bookmark_update.model_dump(exclude_unset=True).items():
        setattr(db_bookmark, key, value)
    _commit(db)
    db.refresh(db_bookmark)
    return db_bookmark


def delete_bookmark(db: Session, bookmark_id: int):
    db_bookmark = db.query(models.Bookmark).filter(models.Bookmark.id == bookmark_id).first()
    if not db_bookmark:
        return False
    db.delete(db_bookmark)
    _commit(db)
    return True


# 以下旧游戏 CRUD 仅用于数据库兼容，不再暴露公开路由。
def get_game_by_slug(db: Session, slug: str):
    return db.query(models.Game).filter(models.Game.slug == slug).first()


def get_games(db: Session, active_only: bool = True):
    query = db.query(models.Game)
    if active_only:
        query = query.filter(models.Game.is_active.is_(True))
    return query.order_by(models.Game.created_at.desc()).all()


def create_game(db: Session, game: schemas.GameCreate):
    db_game = models.Game(**game.model_dump())
    db.add(db_game)
    _commit(db, "Game slug already exists")
    db.refresh(db_game)
    return db_game


def get_redemption_codes(db: Session, limit: int = 100):
    return db.query(models.RedemptionCode).order_by(models.RedemptionCode.created_at.desc()).limit(limit).all()


def create_redemption_code(db: Session, code: str, game_id: int, ip_address: str = None):
    db_code = models.RedemptionCode(
        code=code,
        game_id=game_id,
        ip_address=ip_address,
        status="unused",
    )
    db.add(db_code)
    _commit(db, "Redemption code already exists")
    db.refresh(db_code)
    return db_code


def delete_redemption_code(db: Session, code_id: int):
    db_code = db.query(models.RedemptionCode).filter(models.RedemptionCode.id == code_id).first()
    if not db_code:
        return False
    db.delete(db_code)
    _commit(db)
    return True


def clear_all_redemption_codes(db: Session):
    try:
        db.query(models.RedemptionCode).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
