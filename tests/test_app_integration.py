import binascii
import struct
import zlib


def _post_payload(**overrides):
    payload = {
        "title": "集成测试文章",
        "slug": "integration-post",
        "content": "正文",
        "summary": "摘要",
        "category": "测试",
        "tags": "pytest,FastAPI",
        "is_published": True,
    }
    payload.update(overrides)
    return payload


def _login(app_bundle):
    response = app_bundle.client.post(
        "/api/auth/login",
        json={
            "username": "test-admin",
            "password": "test-admin-password-2026",
        },
    )
    assert response.status_code == 200, response.text
    return response


def _png_chunk(chunk_type, data):
    checksum = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _tiny_png():
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    image_data = zlib.compress(b"\x00\xff\x00\x00")
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", image_data)
        + _png_chunk(b"IEND", b"")
    )


def _response_items(response):
    payload = response.json()
    if isinstance(payload, list):
        return payload
    return payload.get("results", payload.get("items", []))


def test_healthz_uses_temporary_database(app_bundle):
    response = app_bundle.client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}
    assert app_bundle.database_path.exists()
    assert app_bundle.database_path.parent == app_bundle.upload_dir.parent


def test_anonymous_admin_redirect_and_write_api_rejection(app_bundle):
    admin_response = app_bundle.client.get("/admin", follow_redirects=False)
    api_response = app_bundle.client.post(
        "/api/posts",
        json=_post_payload(),
    )

    assert admin_response.status_code == 303
    assert admin_response.headers["location"] == "/login"
    assert api_response.status_code == 401
    assert api_response.json()["detail"] == "Not authenticated"


def test_login_sets_hardened_cookie_without_returning_token(app_bundle):
    response = _login(app_bundle)
    payload = response.json()
    set_cookie = response.headers["set-cookie"]
    normalized_cookie = set_cookie.lower()

    assert payload == {"message": "Login successful"}
    assert "token" not in payload
    assert set_cookie.startswith(f"{app_bundle.config.COOKIE_NAME}=")
    assert "httponly" in normalized_cookie
    assert "secure" in normalized_cookie
    assert "samesite=strict" in normalized_cookie
    assert "path=/" in normalized_cookie
    assert "max-age=604800" in normalized_cookie


def test_draft_is_hidden_from_anonymous_but_visible_to_admin(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        db.add(
            app_bundle.models.Post(
                title="仅管理员可见草稿",
                slug="private-draft",
                content="draft-body-marker",
                summary="draft-summary-marker",
                category="测试",
                tags="draft",
                is_published=False,
            )
        )
        db.commit()

    anonymous_response = app_bundle.client.get("/blog/private-draft")
    assert anonymous_response.status_code == 404

    _login(app_bundle)
    admin_response = app_bundle.client.get("/blog/private-draft")
    assert admin_response.status_code == 200
    assert "仅管理员可见草稿" in admin_response.text
    assert "draft-body-marker" in admin_response.text


def test_search_never_returns_unpublished_posts(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        db.add_all(
            [
                app_bundle.models.Post(
                    title="visibility-marker published",
                    slug="visible-search-result",
                    content="public search body",
                    summary="visibility-marker public summary",
                    category="测试",
                    tags="search",
                    is_published=True,
                ),
                app_bundle.models.Post(
                    title="visibility-marker draft",
                    slug="hidden-search-result",
                    content="private search body",
                    summary="visibility-marker private summary",
                    category="测试",
                    tags="search",
                    is_published=False,
                ),
            ]
        )
        db.commit()

    response = app_bundle.client.get("/api/search", params={"q": "visibility-marker"})

    assert response.status_code == 200, response.text
    items = _response_items(response)
    titles = {item["title"] for item in items}
    assert "visibility-marker published" in titles
    assert "visibility-marker draft" not in titles
    assert all(item.get("url") != "/blog/hidden-search-result" for item in items)


def test_markdown_html_and_dangerous_protocols_are_sanitized(app_bundle):
    _login(app_bundle)
    malicious_content = """
**safe-marker**

<script>window.__integration_xss_probe__ = true</script>

[bad-link](javascript:alert(937))

<img src="javascript:integration-xss-probe" onerror="integration-xss-probe">

<a href="data:text/html,integration-xss-probe">bad raw link</a>
"""
    create_response = app_bundle.client.post(
        "/api/posts",
        json=_post_payload(slug="markdown-safety", content=malicious_content),
    )
    assert create_response.status_code == 201, create_response.text

    app_bundle.client.cookies.clear()
    detail_response = app_bundle.client.get("/blog/markdown-safety")
    rendered = detail_response.text.lower()

    assert detail_response.status_code == 200
    assert "<strong>safe-marker</strong>" in rendered
    assert "window.__integration_xss_probe__" not in rendered
    assert "javascript:alert(937)" not in rendered
    assert "javascript:integration-xss-probe" not in rendered
    assert "data:text/html,integration-xss-probe" not in rendered
    assert 'onerror="integration-xss-probe"' not in rendered


def test_schemas_reject_empty_fields_and_dangerous_urls(app_bundle):
    _login(app_bundle)

    invalid_requests = [
        ("/api/posts", _post_payload(title="   ")),
        ("/api/posts", _post_payload(slug="")),
        (
            "/api/nav_links",
            {
                "title": "危险导航",
                "url": "javascript:alert(1)",
                "category": "测试",
            },
        ),
        (
            "/api/bookmarks",
            {
                "title": "危险收藏",
                "url": "https://user:password@example.com/private",
                "tags": "security",
            },
        ),
    ]

    for endpoint, payload in invalid_requests:
        response = app_bundle.client.post(endpoint, json=payload)
        assert response.status_code == 422, (endpoint, response.text)


def test_duplicate_post_slug_returns_conflict(app_bundle):
    _login(app_bundle)
    first_response = app_bundle.client.post(
        "/api/posts",
        json=_post_payload(slug="duplicate-slug", title="第一篇"),
    )
    second_response = app_bundle.client.post(
        "/api/posts",
        json=_post_payload(slug="duplicate-slug", title="第二篇"),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert "slug" in second_response.json()["detail"].lower()


def test_bookmark_can_be_updated(app_bundle):
    _login(app_bundle)
    create_response = app_bundle.client.post(
        "/api/bookmarks",
        json={
            "title": "待编辑收藏",
            "url": "https://example.com/original",
            "description": "原描述",
            "tags": "old",
        },
    )
    assert create_response.status_code == 201, create_response.text
    bookmark_id = create_response.json()["id"]

    update_response = app_bundle.client.put(
        f"/api/bookmarks/{bookmark_id}",
        json={
            "title": "已编辑收藏",
            "url": "https://example.com/updated",
            "description": "新描述",
            "tags": "new,updated",
        },
    )

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["title"] == "已编辑收藏"
    assert update_response.json()["tags"] == "new,updated"


def test_bookmark_tag_filter_is_applied_before_pagination(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        db.add_all(
            [
                app_bundle.models.Bookmark(
                    title="目标收藏一",
                    url="https://example.com/target-one",
                    description="target-one-marker",
                    tags="Python, 后端",
                ),
                app_bundle.models.Bookmark(
                    title="无关收藏",
                    url="https://example.com/unrelated",
                    description="unrelated-marker",
                    tags="前端",
                ),
                app_bundle.models.Bookmark(
                    title="目标收藏二",
                    url="https://example.com/target-two",
                    description="target-two-marker",
                    tags="python,测试",
                ),
                app_bundle.models.Bookmark(
                    title="带空格标签",
                    url="https://example.com/with-space",
                    description="machine-learning-marker",
                    tags="Machine Learning",
                ),
                app_bundle.models.Bookmark(
                    title="无空格标签",
                    url="https://example.com/without-space",
                    description="machinelearning-marker",
                    tags="MachineLearning",
                ),
            ]
        )
        db.commit()

    first_page = app_bundle.client.get(
        "/bookmarks",
        params={"tag": "PYTHON", "page": 1, "page_size": 1},
    )
    second_page = app_bundle.client.get(
        "/bookmarks",
        params={"tag": "Python", "page": 2, "page_size": 1},
    )
    spaced_tag_page = app_bundle.client.get(
        "/bookmarks",
        params={"tag": "Machine Learning", "page_size": 10},
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert "unrelated-marker" not in first_page.text
    assert "unrelated-marker" not in second_page.text
    assert "target-one-marker" in first_page.text or "target-two-marker" in first_page.text
    assert "target-one-marker" in second_page.text or "target-two-marker" in second_page.text
    assert "tag=python" in first_page.text.lower()
    assert first_page.text.lower().count(">python</a>") == 1
    assert "第 1 / 2 页" in first_page.text
    assert "第 2 / 2 页" in second_page.text
    assert "machine-learning-marker" in spaced_tag_page.text
    assert "machinelearning-marker" not in spaced_tag_page.text


def test_out_of_range_pages_are_clamped(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        db.add_all(
            [
                app_bundle.models.Post(
                    title="分页文章一",
                    slug="pagination-post-one",
                    content="pagination-post-one-marker",
                    summary="分页一",
                    category="测试",
                    tags="pagination",
                    is_published=True,
                ),
                app_bundle.models.Post(
                    title="分页文章二",
                    slug="pagination-post-two",
                    content="pagination-post-two-marker",
                    summary="分页二",
                    category="测试",
                    tags="pagination",
                    is_published=True,
                ),
            ]
        )
        db.commit()

    public_response = app_bundle.client.get(
        "/blog",
        params={"page": 999, "page_size": 1},
    )
    _login(app_bundle)
    admin_response = app_bundle.client.get(
        "/admin",
        params={"post_page": 999, "bookmark_page": 999, "page_size": 1},
    )

    assert public_response.status_code == 200
    assert admin_response.status_code == 200
    assert "第 2 / 2 页" in public_response.text
    assert "第 999" not in public_response.text
    assert "第 2 / 2 页" in admin_response.text
    assert "第 999" not in admin_response.text


def test_upload_requires_authentication(app_bundle):
    response = app_bundle.client.post(
        "/api/upload",
        files={"file": ("pixel.png", _tiny_png(), "image/png")},
    )

    assert response.status_code == 401
    assert not app_bundle.upload_dir.exists() or not any(app_bundle.upload_dir.iterdir())


def test_upload_rejects_svg_disguised_content_and_oversized_file(
    app_bundle,
    authenticated_client,
):
    svg_response = authenticated_client.post(
        "/api/upload",
        files={"file": ("vector.svg", b"<svg></svg>", "image/svg+xml")},
    )
    disguised_response = authenticated_client.post(
        "/api/upload",
        files={"file": ("fake.png", b"not-a-real-png", "image/png")},
    )
    oversized_png = b"\x89PNG\r\n\x1a\n" + (b"x" * 1024)
    oversized_response = authenticated_client.post(
        "/api/upload",
        files={"file": ("large.png", oversized_png, "image/png")},
    )

    assert svg_response.status_code == 400
    assert disguised_response.status_code == 400
    assert oversized_response.status_code == 413
    assert not any(app_bundle.upload_dir.iterdir())


def test_valid_small_png_is_persisted_and_served(app_bundle, authenticated_client):
    png_data = _tiny_png()
    response = authenticated_client.post(
        "/api/upload",
        files={"file": ("pixel.png", png_data, "image/png")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["url"].startswith("/uploads/")
    assert payload["url"].endswith(".png")
    assert payload["size"] == len(png_data)

    stored_path = app_bundle.upload_dir / payload["url"].rsplit("/", 1)[-1]
    assert stored_path.read_bytes() == png_data

    served_response = authenticated_client.get(payload["url"])
    assert served_response.status_code == 200
    assert served_response.content == png_data
    assert served_response.headers["x-content-type-options"] == "nosniff"


def test_logout_revokes_the_previous_cookie_token(app_bundle):
    _login(app_bundle)
    cookie_name = app_bundle.config.COOKIE_NAME
    old_token = app_bundle.client.cookies.get(cookie_name)
    assert old_token

    logout_response = app_bundle.client.post("/api/auth/logout")
    delete_cookie_header = logout_response.headers["set-cookie"].lower()

    assert logout_response.status_code == 200
    assert "max-age=0" in delete_cookie_header
    assert cookie_name not in app_bundle.client.cookies

    replay_response = app_bundle.client.post(
        "/api/posts",
        headers={"Cookie": f"{cookie_name}={old_token}"},
        json=_post_payload(slug="revoked-token-replay"),
    )
    assert replay_response.status_code == 401
