from sqlalchemy.orm import Session
from app import models, schemas

# Post CRUD operations
def get_post(db: Session, post_id: int):
    return db.query(models.Post).filter(models.Post.id == post_id).first()

def get_post_by_slug(db: Session, slug: str):
    return db.query(models.Post).filter(models.Post.slug == slug).first()

def get_posts(db: Session, skip: int = 0, limit: int = 100, published_only: bool = True):
    query = db.query(models.Post)
    if published_only:
        query = query.filter(models.Post.is_published == True)
    return query.order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()

def create_post(db: Session, post: schemas.PostCreate):
    db_post = models.Post(
        title=post.title,
        slug=post.slug,
        content=post.content,
        summary=post.summary,
        category=post.category,
        tags=post.tags,
        is_published=post.is_published
    )
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post

def update_post(db: Session, post_id: int, post_update: schemas.PostUpdate):
    db_post = get_post(db, post_id)
    if not db_post:
        return None
    
    update_data = post_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_post, key, value)
        
    db.commit()
    db.refresh(db_post)
    return db_post

def delete_post(db: Session, post_id: int):
    db_post = get_post(db, post_id)
    if db_post:
        db.delete(db_post)
        db.commit()
        return True
    return False

def increment_post_views(db: Session, post_id: int):
    db_post = get_post(db, post_id)
    if db_post:
        db_post.views += 1
        db.commit()
        db.refresh(db_post)
    return db_post


# NavLink CRUD operations
def get_nav_links(db: Session):
    return db.query(models.NavLink).order_by(models.NavLink.order.asc(), models.NavLink.title.asc()).all()

def create_nav_link(db: Session, nav_link: schemas.NavLinkCreate):
    db_link = models.NavLink(
        title=nav_link.title,
        url=nav_link.url,
        description=nav_link.description,
        category=nav_link.category,
        icon=nav_link.icon,
        order=nav_link.order
    )
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link

def update_nav_link(db: Session, link_id: int, link_update: schemas.NavLinkUpdate):
    db_link = db.query(models.NavLink).filter(models.NavLink.id == link_id).first()
    if not db_link:
        return None
    
    update_data = link_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_link, key, value)
        
    db.commit()
    db.refresh(db_link)
    return db_link

def delete_nav_link(db: Session, link_id: int):
    db_link = db.query(models.NavLink).filter(models.NavLink.id == link_id).first()
    if db_link:
        db.delete(db_link)
        db.commit()
        return True
    return False


# Bookmark CRUD operations
def get_bookmarks(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Bookmark).order_by(models.Bookmark.created_at.desc()).offset(skip).limit(limit).all()

def create_bookmark(db: Session, bookmark: schemas.BookmarkCreate):
    db_bookmark = models.Bookmark(
        title=bookmark.title,
        url=bookmark.url,
        description=bookmark.description,
        tags=bookmark.tags
    )
    db.add(db_bookmark)
    db.commit()
    db.refresh(db_bookmark)
    return db_bookmark

def delete_bookmark(db: Session, bookmark_id: int):
    db_bookmark = db.query(models.Bookmark).filter(models.Bookmark.id == bookmark_id).first()
    if db_bookmark:
        db.delete(db_bookmark)
        db.commit()
        return True
    return False
