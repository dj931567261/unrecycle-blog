import binascii
import struct
import xml.etree.ElementTree as ET
import zlib

from fastapi.testclient import TestClient


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


def test_security_policy_allows_cloudflare_web_analytics(app_bundle):
    response = app_bundle.client.get("/")
    content_security_policy = response.headers["content-security-policy"]

    assert "https://static.cloudflareinsights.com" in content_security_policy
    assert "connect-src 'self' https://cloudflareinsights.com" in content_security_policy


def test_article_content_is_not_hidden_by_reveal_animation(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        db.add(
            app_bundle.models.Post(
                title="长文章显示测试",
                slug="long-article-visibility",
                content=("## 章节\n\nlong-article-visible-marker\n\n" * 400),
                summary="验证长文章正文不会被滚动动画永久隐藏",
                category="测试",
                tags="visibility",
                is_published=True,
            )
        )
        db.commit()

    response = app_bundle.client.get("/blog/long-article-visibility")

    assert response.status_code == 200
    assert "long-article-visible-marker" in response.text
    assert '<div class="blog-main-content">' in response.text
    assert 'class="blog-main-content" data-reveal' not in response.text


def test_browser_404_uses_custom_page_while_api_keeps_json(app_bundle):
    page_response = app_bundle.client.get(
        "/missing-page",
        headers={"Accept": "text/html"},
    )
    api_response = app_bundle.client.get(
        "/api/missing-endpoint",
        headers={"Accept": "text/html"},
    )

    assert page_response.status_code == 404
    assert page_response.headers["content-type"].startswith("text/html")
    assert "404" in page_response.text
    assert "这条路径没有留下内容" in page_response.text
    assert "/missing-page" in page_response.text
    assert "accept" in page_response.headers["vary"].lower()
    assert page_response.headers["cache-control"] == "no-store"

    assert api_response.status_code == 404
    assert api_response.headers["content-type"].startswith("application/json")
    assert api_response.json() == {"detail": "Not Found"}
    assert "accept" in api_response.headers["vary"].lower()


def test_browser_500_uses_custom_page_without_leaking_exception(app_bundle):
    def raise_page_error():
        raise RuntimeError("sensitive-error-marker")

    app_bundle.main.app.add_api_route(
        "/__integration__/page-error",
        raise_page_error,
        methods=["GET"],
    )
    app_bundle.main.app.add_api_route(
        "/api/__integration__/page-error",
        raise_page_error,
        methods=["GET"],
    )

    with TestClient(
        app_bundle.main.app,
        base_url="https://testserver",
        raise_server_exceptions=False,
    ) as client:
        page_response = client.get(
            "/__integration__/page-error",
            headers={"Accept": "text/html"},
        )
        api_response = client.get(
            "/api/__integration__/page-error",
            headers={"Accept": "text/html"},
        )

    assert page_response.status_code == 500
    assert page_response.headers["content-type"].startswith("text/html")
    assert "这里遇到了一点意外" in page_response.text
    assert "REFERENCE" in page_response.text
    assert "sensitive-error-marker" not in page_response.text
    assert page_response.headers["cache-control"] == "no-store"
    assert page_response.headers["x-content-type-options"] == "nosniff"

    assert api_response.status_code == 500
    assert api_response.headers["content-type"].startswith("application/json")
    assert api_response.json()["detail"] == "Internal server error"
    assert "reference" in api_response.json()
    assert "sensitive-error-marker" not in api_response.text


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


def test_post_editor_is_protected_and_loads_full_content_on_demand(app_bundle):
    with app_bundle.database.SessionLocal() as db:
        post = app_bundle.models.Post(
            title="独立编辑器测试文章",
            slug="post-editor-integration",
            content="post-editor-content-must-not-be-in-admin-list",
            summary="编辑器集成测试",
            category="编辑器测试",
            tags="editor,autosave",
            is_published=True,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    anonymous_new = app_bundle.client.get(
        "/admin/posts/new",
        follow_redirects=False,
    )
    anonymous_edit = app_bundle.client.get(
        f"/admin/posts/{post_id}/edit",
        follow_redirects=False,
    )
    anonymous_api = app_bundle.client.get(f"/api/posts/{post_id}")
    anonymous_detail = app_bundle.client.get("/blog/post-editor-integration")

    assert anonymous_new.status_code == 303
    assert anonymous_new.headers["location"] == "/login?next=/admin/posts/new"
    assert anonymous_edit.status_code == 303
    assert anonymous_edit.headers["location"] == (
        f"/login?next=/admin/posts/{post_id}/edit"
    )
    assert anonymous_api.status_code == 401
    assert f'/admin/posts/{post_id}/edit' not in anonymous_detail.text

    _login(app_bundle)

    new_editor = app_bundle.client.get("/admin/posts/new")
    edit_editor = app_bundle.client.get(f"/admin/posts/{post_id}/edit")
    post_api = app_bundle.client.get(f"/api/posts/{post_id}")
    admin_page = app_bundle.client.get("/admin")
    admin_detail = app_bundle.client.get("/blog/post-editor-integration")

    assert new_editor.status_code == 200
    assert edit_editor.status_code == 200
    assert "/static/css/post-editor.css" in new_editor.text
    assert "/static/js/admin-post-editor.js?v=1.4" in new_editor.text
    assert 'data-markdown-action="heading-2"' in new_editor.text
    assert 'data-markdown-action="heading-3"' in new_editor.text
    assert 'data-markdown-action="heading-4"' in new_editor.text
    assert "post-editor-content-must-not-be-in-admin-list" not in edit_editor.text

    assert post_api.status_code == 200
    assert post_api.headers["cache-control"] == "no-store"
    assert post_api.json()["content"] == "post-editor-content-must-not-be-in-admin-list"
    assert post_api.json()["is_published"] is True

    assert admin_page.status_code == 200
    assert "post-editor-content-must-not-be-in-admin-list" not in admin_page.text
    assert f'href="/admin/posts/{post_id}/edit"' in admin_page.text
    assert f'href="/admin/posts/{post_id}/edit"' in admin_detail.text


def test_post_updates_use_etag_to_prevent_silent_overwrite(app_bundle):
    _login(app_bundle)

    created = app_bundle.client.post(
        "/api/posts",
        json=_post_payload(slug="etag-editor-post", is_published=False),
    )
    assert created.status_code == 201
    post_id = created.json()["id"]
    original_etag = created.headers["etag"]
    original_revision = created.headers["x-post-revision"]
    assert original_etag.startswith('"') and original_etag.endswith('"')
    assert original_etag == f'"{original_revision}"'
    assert len(original_revision) == 64

    loaded = app_bundle.client.get(f"/api/posts/{post_id}")
    assert loaded.status_code == 200
    assert loaded.headers["etag"] == original_etag
    assert loaded.headers["x-post-revision"] == original_revision

    first_update = app_bundle.client.put(
        f"/api/posts/{post_id}",
        headers={"If-Match": original_etag},
        json={"title": "第一个编辑窗口保存的标题"},
    )
    assert first_update.status_code == 200
    updated_etag = first_update.headers["etag"]
    updated_revision = first_update.headers["x-post-revision"]
    assert updated_etag != original_etag
    assert updated_etag == f'"{updated_revision}"'

    weak_proxy_update = app_bundle.client.put(
        f"/api/posts/{post_id}",
        headers={"If-Match": f"W/{updated_etag}"},
        json={"title": "代理弱化 ETag 后仍可保存"},
    )
    assert weak_proxy_update.status_code == 200
    proxy_revision = weak_proxy_update.headers["x-post-revision"]
    assert proxy_revision != updated_revision

    revision_header_update = app_bundle.client.put(
        f"/api/posts/{post_id}",
        headers={"X-Post-Revision": proxy_revision},
        json={"title": "应用版本头保存成功"},
    )
    assert revision_header_update.status_code == 200
    latest_revision = revision_header_update.headers["x-post-revision"]
    assert latest_revision != proxy_revision

    stale_legacy_update = app_bundle.client.put(
        f"/api/posts/{post_id}",
        headers={"If-Match": f"W/{updated_etag}"},
        json={"title": "过期弱 ETag 不应覆盖"},
    )
    assert stale_legacy_update.status_code == 409
    assert stale_legacy_update.headers["x-post-revision"] == latest_revision

    stale_update = app_bundle.client.put(
        f"/api/posts/{post_id}",
        headers={
            "X-Post-Revision": original_revision,
            "If-Match": f'"{latest_revision}"',
        },
        json={"title": "过期编辑窗口不应覆盖"},
    )
    assert stale_update.status_code == 409
    assert stale_update.headers["etag"] == f'"{latest_revision}"'
    assert stale_update.headers["x-post-revision"] == latest_revision
    assert "another session" in stale_update.json()["detail"].lower()

    latest = app_bundle.client.get(f"/api/posts/{post_id}")
    assert latest.json()["title"] == "应用版本头保存成功"


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


def test_mixed_markdown_list_markers_keep_ordered_and_unordered_types(app_bundle):
    content = """1. **Function Calling**:
- Skills bullet marker
2. **System Prompt**:
- Prompt bullet marker
3. **Reasoning Chain**:
- Chain bullet marker

1. Nested parent
   - Nested bullet marker
2. Nested second
   - Second nested marker
"""
    with app_bundle.database.SessionLocal() as db:
        db.add(
            app_bundle.models.Post(
                title="混合列表渲染测试",
                slug="mixed-list-markers",
                content=content,
                summary="验证有序和无序列表不会互相转换",
                category="测试",
                tags="markdown,list",
                is_published=True,
            )
        )
        db.commit()

    response = app_bundle.client.get("/blog/mixed-list-markers")
    rendered = app_bundle.main.render_markdown(content)
    root = ET.fromstring(f"<root>{rendered}</root>")

    assert response.status_code == 200
    assert [element.tag for element in root] == [
        "ol",
        "ul",
        "ol",
        "ul",
        "ol",
        "ul",
        "ol",
    ]
    assert root[2].attrib == {"start": "2"}
    assert root[4].attrib == {"start": "3"}
    assert "".join(root[1][0].itertext()) == "Skills bullet marker"
    assert "".join(root[3][0].itertext()) == "Prompt bullet marker"
    assert "".join(root[5][0].itertext()) == "Chain bullet marker"

    nested_list = root[6]
    assert len(nested_list.findall("./li")) == 2
    assert " ".join("".join(nested_list[0].itertext()).split()) == (
        "Nested parent Nested bullet marker"
    )
    assert " ".join("".join(nested_list[1].itertext()).split()) == (
        "Nested second Second nested marker"
    )
    assert nested_list[0].find("./ul/li").text == "Nested bullet marker"
    assert nested_list[1].find("./ul/li").text == "Second nested marker"

    assert "<ol start=\"2\">" in response.text
    assert "<ol start=\"3\">" in response.text


def test_markdown_code_blocks_are_not_changed_by_list_preprocessor(app_bundle):
    content = """```markdown
1. fenced ordered
- fenced unordered
```

~~~text
- tilde unordered
2. tilde ordered
~~~

<pre>
- raw unordered
3. raw ordered
</pre>
"""

    rendered = app_bundle.main.render_markdown(content)
    root = ET.fromstring(f"<root>{rendered}</root>")
    code_blocks = root.findall("./pre")

    assert len(code_blocks) == 3
    assert code_blocks[0].find("code").text == (
        "1. fenced ordered\n- fenced unordered\n"
    )
    assert code_blocks[1].find("code").text == (
        "- tilde unordered\n2. tilde ordered\n"
    )
    assert code_blocks[2].text == "\n- raw unordered\n3. raw ordered\n"
    assert root.findall(".//ol") == []
    assert root.findall(".//ul") == []


def test_nested_mixed_list_dedent_keeps_parent_sibling(app_bundle):
    content = """1. parent
   - nested unordered
   1. nested ordered marker
2. parent sibling
"""

    rendered = app_bundle.main.render_markdown(content)
    root = ET.fromstring(f"<root>{rendered}</root>")
    outer_list = root.find("./ol")

    assert outer_list is not None
    assert len(outer_list.findall("./li")) == 2
    assert "".join(outer_list[1].itertext()) == "parent sibling"
    child_lists = [
        child
        for child in outer_list[0]
        if child.tag in {"ol", "ul"}
    ]
    assert [child.tag for child in child_lists] == ["ul", "ol"]
    assert "".join(child_lists[0].itertext()).strip() == "nested unordered"
    assert "".join(child_lists[1].itertext()).strip() == "nested ordered marker"


def test_mixed_lists_inside_blockquote_keep_marker_types(app_bundle):
    root_mixed = """> 1. quoted ordered
> - quoted unordered
> 2. quoted ordered again
"""

    rendered = app_bundle.main.render_markdown(root_mixed)
    root = ET.fromstring(f"<root>{rendered}</root>")
    blockquote = root.find("./blockquote")

    assert blockquote is not None
    assert [child.tag for child in blockquote] == ["ol", "ul", "ol"]
    assert blockquote[2].attrib == {"start": "2"}


def test_list_preprocessor_preserves_root_indents_and_indented_code(app_bundle):
    for indent in range(1, 4):
        rendered = app_bundle.main.render_markdown(f"{' ' * indent}- root item")
        root = ET.fromstring(f"<root>{rendered}</root>")

        assert root.find("./ul/li").text == "root item"
        assert root.find("./pre") is None

    indented_code = """Paragraph

    - four spaces
     - five spaces
      1. six spaces
        - eight spaces
"""
    rendered = app_bundle.main.render_markdown(indented_code)
    root = ET.fromstring(f"<root>{rendered}</root>")

    assert root.find("./pre/code").text == (
        "- four spaces\n"
        " - five spaces\n"
        "  1. six spaces\n"
        "    - eight spaces\n"
    )
    assert root.findall(".//ul") == []
    assert root.findall(".//ol") == []


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
