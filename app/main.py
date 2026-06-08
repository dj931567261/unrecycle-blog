import os
import shutil
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, status, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import markdown

from app import crud, models, schemas, auth
from app.database import engine, Base, get_db
from app.config import UPLOAD_DIR, ADMIN_USERNAME

# Initialize database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Unrecycle-Me", description="Personal Developer Dashboard & Blog")

import time
@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    print(f"⌛ [PROFILER] Request to {request.url.path} took {duration:.4f} seconds")
    return response

# Auto-seed database with initial content on startup
from app.database import SessionLocal
@app.on_event("startup")
def seed_initial_data():
    db = SessionLocal()
    try:
        # Check and seed NavLinks
        if db.query(models.NavLink).count() == 0:
            nav_links = [
                models.NavLink(title="FastAPI 文档", url="https://fastapi.tiangolo.com", description="Python 现代 Web 框架官方中文文档", category="技术文档", icon="⚡", order=1),
                models.NavLink(title="MDN Web", url="https://developer.mozilla.org/zh-CN", description="最权威的 Web 前端开发技术参考资料", category="技术文档", icon="📖", order=2),
                models.NavLink(title="GitHub", url="https://github.com", description="全球开源代码托管与协作开发社区", category="常用网址", icon="🐙", order=1),
                models.NavLink(title="Can I Use", url="https://caniuse.com", description="前端浏览器兼容性查询工具", category="常用网址", icon="🌐", order=2),
            ]
            db.add_all(nav_links)
            db.commit()
            
        # Check and seed Posts
        if db.query(models.Post).count() == 0:
            first_post = models.Post(
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
                is_published=True
            )
            db.add(first_post)
            db.commit()
            
        # Check and seed Bookmarks
        if db.query(models.Bookmark).count() == 0:
            bookmarks = [
                models.Bookmark(title="Prism.js - 轻量级代码语法高亮工具", url="https://prismjs.com", description="一个非常小巧、速度极快的客户端代码高亮库，本站的技术文章代码块就是用它高亮渲染的。", tags="Frontend,Tools"),
                models.Bookmark(title="FastAPI - Official Documentation", url="https://fastapi.tiangolo.com", description="FastAPI standard doc site", tags="Backend,Python")
            ]
            db.add_all(bookmarks)
            db.commit()

        # Check and seed Games
        db.query(models.Game).filter(models.Game.slug.in_(["sudoku", "riddle"])).delete(synchronize_session=False)
        db.commit()

        if db.query(models.Game).filter(models.Game.slug.in_(["minesweeper", "sliding-puzzle"])).count() == 0:
            games = [
                models.Game(
                    title="战损级 RPG 扫雷",
                    slug="minesweeper",
                    description="融合了 RPG 生命值与道具机制，以及心跳倒计时的定时雷扫雷挑战！避开地雷，解救危机，获取专属兑换码。",
                    difficulty="困难",
                    secret_hash=None,
                    is_active=True
                ),
                models.Game(
                    title="极客拼图滑块",
                    slug="sliding-puzzle",
                    description="经典数字华容道（8宫格拼图）。滑动滑块，将数字拼回顺序（1-8 + 空白格），通关即可得到兑换码。",
                    difficulty="中等",
                    secret_hash=None,
                    is_active=True
                )
            ]
            db.add_all(games)
            db.commit()
    finally:
        db.close()

# Ensure static and template directories exist
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/static/css", exist_ok=True)
os.makedirs("app/static/js", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

# Mount static files with browser cache headers (Cache-Control)
class CachedStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=604800"
        return response

app.mount("/static", CachedStaticFiles(directory="app/static"), name="static")

# Configure templates
templates = Jinja2Templates(directory="app/templates")

def render_markdown(text: str) -> str:
    if not text:
        return ""
    # Extensions: fenced_code (code blocks), tables, toc (table of contents)
    return markdown.markdown(text, extensions=['fenced_code', 'tables', 'toc', 'nl2br'])

# Add markdown filter to Jinja2
templates.env.filters["markdown"] = render_markdown

# Add template helper to format dates
def format_datetime(value, format="%Y-%m-%d"):
    if not value:
        return ""
    if isinstance(value, str):
        from datetime import datetime
        # Try parsing standard formats first
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).strftime(format)
            except ValueError:
                continue
        # If parsing fails, fall back to extracting the date prefix if it looks like a date
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return value[:10]
        return value
    try:
        return value.strftime(format)
    except AttributeError:
        return str(value)

templates.env.filters["datetime"] = format_datetime



# ---------------- PAGE ROUTES (HTML) ----------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    nav_links = crud.get_nav_links(db)
    recent_posts = crud.get_posts(db, limit=5, published_only=True)
    bookmarks = crud.get_bookmarks(db, limit=6)
    
    # Group nav links by category
    categorized_links = {}
    for link in nav_links:
        categorized_links.setdefault(link.category, []).append(link)
        
    return templates.TemplateResponse(request, "index.html", {
        "categorized_links": categorized_links,
        "recent_posts": recent_posts,
        "bookmarks": bookmarks,
        "is_admin": current_user is not None
    })

@app.get("/blog", response_class=HTMLResponse)
async def blog_list(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    posts = crud.get_posts(db, published_only=(current_user is None))
    return templates.TemplateResponse(request, "blog_list.html", {
        "posts": posts,
        "is_admin": current_user is not None
    })

@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_detail(request: Request, slug: str, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    post = crud.get_post_by_slug(db, slug)
    if not post:
        raise HTTPException(status_code=404, detail="Article not found")
        
    # Increment view count if not admin
    if not current_user:
        crud.increment_post_views(db, post.id)
        
    return templates.TemplateResponse(request, "blog_detail.html", {
        "post": post,
        "is_admin": current_user is not None
    })

@app.get("/bookmarks", response_class=HTMLResponse)
async def bookmarks_list(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    bookmarks = crud.get_bookmarks(db, limit=100)
    
    # Extract unique tags from bookmarks
    all_tags = set()
    for b in bookmarks:
        if b.tags:
            for t in b.tags.split(','):
                cleaned = t.strip()
                if cleaned:
                    all_tags.add(cleaned)
    sorted_tags = sorted(list(all_tags))
    
    return templates.TemplateResponse(request, "bookmarks.html", {
        "bookmarks": bookmarks,
        "is_admin": current_user is not None,
        "tags": sorted_tags
    })

@app.get("/tools", response_class=HTMLResponse)
async def tools_list_page(request: Request, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    return templates.TemplateResponse(request, "tools_list.html", {
        "is_admin": current_user is not None
    })

@app.get("/tools/{tool_name}", response_class=HTMLResponse)
async def render_tool(request: Request, tool_name: str, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    template_file = f"tools/{tool_name.replace('-', '_')}.html"
    try:
        # Try to locate the template, if it exists serve it
        templates.get_template(template_file)
        return templates.TemplateResponse(request, template_file, {
            "is_admin": current_user is not None
        })
    except Exception:
        raise HTTPException(status_code=404, detail="Tool not found")

# --- Game Center Routes ---
import hmac
import hashlib
import json
import base64
import secrets

GAME_SECRET_KEY = b"unrecycle_rpg_minesweeper_secret"

def sign_game_state(data: dict) -> str:
    json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
    sig = hmac.new(GAME_SECRET_KEY, json_bytes, hashlib.sha256).hexdigest()
    payload = {"data": data, "sig": sig}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

def verify_game_state(payload_str: str) -> Optional[dict]:
    try:
        payload = json.loads(base64.b64decode(payload_str.encode("utf-8")).decode("utf-8"))
        data = payload["data"]
        sig = payload["sig"]
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        expected_sig = hmac.new(GAME_SECRET_KEY, json_bytes, hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_sig):
            return data
    except Exception:
        pass
    return None

class GameVerifyPayload(BaseModel):
    # Common
    token: str
    
    # For Minesweeper
    flags: Optional[List[List[int]]] = None
    mistakes: Optional[int] = 0
    
    # For Sliding Puzzle
    moves: Optional[List[str]] = None

@app.get("/games", response_class=HTMLResponse)
async def games_list_page(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    games = crud.get_games(db, active_only=True)
    return templates.TemplateResponse(request, "games_list.html", {
        "games": games,
        "is_admin": current_user is not None
    })

@app.get("/games/{game_slug}", response_class=HTMLResponse)
async def game_detail_page(request: Request, game_slug: str, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    game = crud.get_game_by_slug(db, game_slug)
    if not game or not game.is_active:
        raise HTTPException(status_code=404, detail="Game not found")
    return templates.TemplateResponse(request, "game_detail.html", {
        "game": game,
        "is_admin": current_user is not None
    })

# API to Start / Scramble the game and return signed state
@app.get("/api/games/{game_slug}/start")
async def start_game(game_slug: str, db: Session = Depends(get_db)):
    game = crud.get_game_by_slug(db, game_slug)
    if not game or not game.is_active:
        raise HTTPException(status_code=404, detail="Game not found")
        
    if game_slug == "minesweeper":
        # Generate 10x10 board with 15 mines (12 regular, 3 bombs)
        import random
        all_cells = [(r, c) for r in range(10) for c in range(10)]
        mine_cells = random.sample(all_cells, 15)
        
        # 3 time-bombs, 12 regular mines
        bombs = mine_cells[:3]
        mines = mine_cells[3:]
        
        state_data = {
            "game": "minesweeper",
            "bombs": bombs,
            "mines": mines
        }
        token = sign_game_state(state_data)
        
        # We only return the Time-Bomb positions to the client (so it can flash them)
        # We do NOT return regular mine positions (these are hidden in the token)
        return {
            "token": token,
            "bombs": bombs
        }
        
    elif game_slug == "sliding-puzzle":
        # Generate solvable 3x3 board
        # Solved board: [1, 2, 3, 4, 5, 6, 7, 8, 0]
        # We make random swaps to scramble it
        import random
        b = [1, 2, 3, 4, 5, 6, 7, 8, 0]
        for _ in range(40):
            idx = b.index(0)
            valid_swaps = []
            if idx >= 3: valid_swaps.append(idx - 3) # Up
            if idx < 6: valid_swaps.append(idx + 3) # Down
            if idx % 3 != 0: valid_swaps.append(idx - 1) # Left
            if idx % 3 != 2: valid_swaps.append(idx + 1) # Right
            swap_idx = random.choice(valid_swaps)
            b[idx], b[swap_idx] = b[swap_idx], b[idx]
            
        state_data = {
            "game": "sliding-puzzle",
            "initial_board": b
        }
        token = sign_game_state(state_data)
        return {
            "token": token,
            "board": b
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid game slug")

@app.post("/api/games/{game_slug}/verify")
async def verify_game(request: Request, game_slug: str, payload: GameVerifyPayload, db: Session = Depends(get_db)):
    game = crud.get_game_by_slug(db, game_slug)
    if not game or not game.is_active:
        raise HTTPException(status_code=404, detail="Game not found")
        
    # Verify signature token
    state_data = verify_game_state(payload.token)
    if not state_data or state_data.get("game") != game_slug:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "failed", "error": "无效的游戏校验数据，请重新开始游戏！"}
        )
        
    verified = False
    
    # 1. Minesweeper validation
    if game_slug == "minesweeper":
        if payload.flags is not None and payload.mistakes is not None:
            # Check that mistakes are under 3
            if payload.mistakes >= 3:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"status": "failed", "error": "生命值已耗尽，挑战失败！"}
                )
            # Check that flags match mines exactly
            # Mines are: bombs + mines
            expected_mines = set((m[0], m[1]) for m in state_data["mines"]) | set((b[0], b[1]) for b in state_data["bombs"])
            user_flags = set((f[0], f[1]) for f in payload.flags)
            
            # Since user might flag other safe spots, they must flag exactly the 15 mines
            verified = (expected_mines == user_flags)
            
    # 2. Sliding Puzzle validation
    elif game_slug == "sliding-puzzle":
        if payload.moves is not None:
            # Simulate moves on initial board
            initial_board = state_data["initial_board"]
            b = list(initial_board)
            for m in payload.moves:
                idx = b.index(0)
                if m == "U" and idx >= 3:
                    b[idx], b[idx - 3] = b[idx - 3], b[idx]
                elif m == "D" and idx < 6:
                    b[idx], b[idx + 3] = b[idx + 3], b[idx]
                elif m == "L" and idx % 3 != 0:
                    b[idx], b[idx - 1] = b[idx - 1], b[idx]
                elif m == "R" and idx % 3 != 2:
                    b[idx], b[idx + 1] = b[idx + 1], b[idx]
            # Check if solved
            verified = (b == [1, 2, 3, 4, 5, 6, 7, 8, 0])
            
    if not verified:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "failed", "error": "校验未通过，请确保答案正确并完成游戏！"}
        )
        
    # Generate redemption code
    code_str = f"UM-{game_slug.upper()[:3]}-{secrets.token_hex(4).upper()}"
    client_ip = request.client.host if request.client else "unknown"
    crud.create_redemption_code(db, code_str, game.id, client_ip)
    
    return {
        "status": "success",
        "code": code_str
    }

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    if current_user:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db), current_user: Optional[str] = Depends(auth.get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    import traceback
    try:
        posts = crud.get_posts(db, published_only=False)
        nav_links = crud.get_nav_links(db)
        bookmarks = crud.get_bookmarks(db, limit=100)
        
        # Convert SQLAlchemy models to dictionaries so Jinja2's tojson filter can serialize them safely
        from datetime import datetime
        def model_to_dict(obj):
            if not obj:
                return {}
            d = {}
            for c in obj.__table__.columns:
                val = getattr(obj, c.name)
                if isinstance(val, datetime):
                    d[c.name] = val.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    d[c.name] = val
            return d

        posts_data = [model_to_dict(p) for p in posts]
        nav_links_data = [model_to_dict(n) for n in nav_links]
        bookmarks_data = [model_to_dict(b) for b in bookmarks]
        
        redemption_codes = crud.get_redemption_codes(db, limit=100)
        codes_data = []
        for rc in redemption_codes:
            d = model_to_dict(rc)
            d["game_title"] = rc.game.title if rc.game else "未知游戏"
            codes_data.append(d)
        
        # Get unique navigation categories with common defaults
        default_categories = ["常用网址", "技术文档", "开发工具", "设计资源"]
        existing_categories = [n.category for n in nav_links if n.category]
        nav_categories = sorted(list(set(default_categories + existing_categories)))
        
        # Get unique bookmark tags
        b_tags = set()
        for b in bookmarks:
            if b.tags:
                for t in b.tags.split(','):
                    cleaned = t.strip()
                    if cleaned:
                        b_tags.add(cleaned)
        sorted_bookmark_tags = sorted(list(b_tags))
        
        return templates.TemplateResponse(request, "admin.html", {
            "posts": posts_data,
            "nav_links": nav_links_data,
            "bookmarks": bookmarks_data,
            "redemption_codes": codes_data,
            "username": current_user,
            "nav_categories": nav_categories,
            "bookmark_tags": sorted_bookmark_tags
        })
    except Exception as e:
        tb = traceback.format_exc()
        print(f"❌ [ADMIN PAGE ERROR]\n{tb}")
        return HTMLResponse(content=f"<h3>Admin Page Error (Debug)</h3><pre>{tb}</pre>", status_code=500)


# ---------------- API ROUTES (JSON) ----------------

# Authentication APIs
@app.post("/api/auth/login")
async def api_login(form_data: schemas.UserLogin, db: Session = Depends(get_db)):
    if not auth.verify_admin_credentials(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    access_token = auth.create_access_token(data={"sub": form_data.username})
    
    # Return JSON response and set cookie
    res = JSONResponse(content={"message": "Login successful", "access_token": access_token})
    res.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=3600 * 24 * 7,  # 7 days
        samesite="lax",
        secure=False  # Set to True in production with HTTPS
    )
    return res

@app.post("/api/auth/logout")
async def api_logout():
    res = JSONResponse(content={"message": "Logged out successfully"})
    res.delete_cookie("access_token")
    return res


# Post APIs
@app.post("/api/posts", response_model=schemas.PostInDB)
async def create_post(post: schemas.PostCreate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    existing = crud.get_post_by_slug(db, post.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")
    return crud.create_post(db, post)

@app.put("/api/posts/{post_id}", response_model=schemas.PostInDB)
async def update_post(post_id: int, post_update: schemas.PostUpdate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    # Check if slug is taken by another post
    if post_update.slug:
        existing = crud.get_post_by_slug(db, post_update.slug)
        if existing and existing.id != post_id:
            raise HTTPException(status_code=400, detail="Slug already exists")
            
    updated = crud.update_post(db, post_id, post_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Post not found")
    return updated

@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    success = crud.delete_post(db, post_id)
    if not success:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Post deleted successfully"}


# NavLink APIs
@app.post("/api/nav_links", response_model=schemas.NavLinkInDB)
async def create_nav_link(nav_link: schemas.NavLinkCreate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    return crud.create_nav_link(db, nav_link)

@app.put("/api/nav_links/{link_id}", response_model=schemas.NavLinkInDB)
async def update_nav_link(link_id: int, link_update: schemas.NavLinkUpdate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    updated = crud.update_nav_link(db, link_id, link_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Navigation link not found")
    return updated

@app.delete("/api/nav_links/{link_id}")
async def delete_nav_link(link_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    success = crud.delete_nav_link(db, link_id)
    if not success:
        raise HTTPException(status_code=404, detail="Navigation link not found")
    return {"message": "Navigation link deleted successfully"}


# Bookmark APIs
@app.post("/api/bookmarks", response_model=schemas.BookmarkInDB)
async def create_bookmark(bookmark: schemas.BookmarkCreate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    return crud.create_bookmark(db, bookmark)

@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    success = crud.delete_bookmark(db, bookmark_id)
    if not success:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"message": "Bookmark deleted successfully"}


# Image Upload API
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), current_user: str = Depends(auth.get_current_user)):
    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    # Generate unique filename
    import uuid
    filename = f"{uuid.uuid4()}{ext}"
    file_path = UPLOAD_DIR / filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    return {"url": f"/static/uploads/{filename}"}


# Redemption Code Admin APIs
@app.delete("/api/codes/{code_id}")
async def delete_redemption_code(code_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    success = crud.delete_redemption_code(db, code_id)
    if not success:
        raise HTTPException(status_code=404, detail="Redemption code not found")
    return {"message": "Redemption code deleted successfully"}

@app.delete("/api/codes")
async def clear_all_redemption_codes(db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    crud.clear_all_redemption_codes(db)
    return {"message": "All redemption codes cleared successfully"}

