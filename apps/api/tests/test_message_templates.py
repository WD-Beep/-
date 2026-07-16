"""话术库租户隔离与 CRUD 测试。"""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile

import pytest
from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.message_template import MessageTemplate
from app.schemas.message_template import MessageTemplateCreate
from app.models.tenant import Product


def _product_b() -> Product:
    suffix = uuid.uuid4().hex[:8]
    return Product(
        workspace_id=1,
        name=f"话术测试产品B-{suffix}",
        slug=f"msg-tpl-b-{suffix}",
        is_default=False,
    )


def test_message_templates_reject_missing_headers():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/api/message-templates",):
                response = await client.get(path)
                assert response.status_code == 422

    asyncio.run(_run())


def test_message_templates_require_specific_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/message-templates",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert response.status_code == 400

    asyncio.run(_run())


def test_message_template_schema_keeps_ai_generation_rules():
    payload = MessageTemplateCreate(
        title="AI outreach framework",
        scenario="first_contact",
        content="Hi {name}",
        generation_rules={
            "tone": "natural",
            "language": "en",
            "min_length": 180,
            "max_length": 300,
            "required_content": ["soft CTA"],
            "forbidden_content": ["guaranteed results"],
        },
        is_default=True,
        source_filename="outreach-framework.docx",
    )

    dumped = payload.model_dump()
    assert dumped["generation_rules"]["min_length"] == 180
    assert dumped["is_default"] is True
    assert dumped["source_filename"] == "outreach-framework.docx"


def test_message_template_schema_rejects_invalid_length_range():
    with pytest.raises(ValueError):
        MessageTemplateCreate(
            title="Invalid range",
            scenario="first_contact",
            content="Hi {name}",
            generation_rules={"min_length": 500, "max_length": 100},
        )


def test_message_template_schema_allows_short_content_but_limits_note():
    payload = MessageTemplateCreate(
        title="Short but allowed",
        scenario="first_contact",
        content="Hi {name}",
        note="Use for concise outreach.",
    )

    assert payload.content == "Hi {name}"
    assert payload.note == "Use for concise outreach."

    with pytest.raises(ValueError):
        MessageTemplateCreate(
            title="Note too long",
            scenario="first_contact",
            content="Hi {name}",
            note="x" * 501,
        )


def test_message_template_upload_parses_text_markdown_and_docx():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with async_session_factory() as db_session:
            product = _product_b()
            db_session.add(product)
            await db_session.commit()
            await db_session.refresh(product)
            product_id = product.id

        docx_buffer = io.BytesIO()
        with zipfile.ZipFile(docx_buffer, "w") as archive:
            archive.writestr(
                "word/document.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>DOCX template line</w:t></w:r></w:p></w:body>
                </w:document>""",
            )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-User-Id": "1", "X-Product-Id": str(product_id)}
            for filename, content, expected in (
                ("template.txt", "Plain text template".encode(), "Plain text template"),
                ("template.md", "# Markdown template".encode(), "# Markdown template"),
                ("template.docx", docx_buffer.getvalue(), "DOCX template line"),
            ):
                response = await client.post(
                    "/api/message-templates/parse-upload",
                    headers=headers,
                    files={"file": (filename, content, "application/octet-stream")},
                )
                assert response.status_code == 200, response.text
                assert expected in response.json()["content"]

        async with async_session_factory() as db_session:
            await db_session.execute(delete(Product).where(Product.id == product_id))
            await db_session.commit()

    asyncio.run(_run())


def test_message_templates_filtered_by_product():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            product_b = _product_b()
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id
            db_session.add_all(
                [
                    MessageTemplate(
                        user_id=1,
                        workspace_id=1,
                        product_id=1,
                        title=f"产品A话术-{suffix}",
                        scenario="first_contact",
                        content="Hello A {name}",
                        tags=["intro"],
                    ),
                    MessageTemplate(
                        user_id=1,
                        workspace_id=1,
                        product_id=product_b_id,
                        title=f"产品B话术-{suffix}",
                        scenario="first_contact",
                        content="Hello B {name}",
                        tags=["intro"],
                    ),
                ]
            )
            await db_session.commit()

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers_a = {"X-User-Id": "1", "X-Product-Id": "1"}
                list_a = await client.get("/api/message-templates", headers=headers_a)
                assert list_a.status_code == 200
                titles_a = {item["title"] for item in list_a.json()["items"]}
                assert f"产品A话术-{suffix}" in titles_a
                assert f"产品B话术-{suffix}" not in titles_a

                create = await client.post(
                    "/api/message-templates",
                    headers=headers_a,
                    json={
                        "title": f"新建话术-{suffix}",
                        "scenario": "quote",
                        "content": "Quote for {product}",
                        "platform": "instagram",
                        "language": "en",
                        "tags": ["quote"],
                    },
                )
                assert create.status_code == 201
                created = create.json()
                assert created["product_id"] == 1
                assert created["user_id"] == 1

                cross = await client.get(
                    f"/api/message-templates/{created['id']}",
                    headers={"X-User-Id": "1", "X-Product-Id": str(product_b_id)},
                )
                assert cross.status_code == 404

                use_resp = await client.post(
                    f"/api/message-templates/{created['id']}/use",
                    headers=headers_a,
                )
                assert use_resp.status_code == 200
                assert use_resp.json()["usage_count"] == 1
                assert use_resp.json()["last_used_at"] is not None

                delete_resp = await client.delete(
                    f"/api/message-templates/{created['id']}",
                    headers=headers_a,
                )
                assert delete_resp.status_code == 204
        finally:
            async with async_session_factory() as db_session:
                await db_session.execute(
                    delete(MessageTemplate).where(MessageTemplate.title.like(f"%{suffix}%"))
                )
                await db_session.execute(delete(Product).where(Product.id == product_b_id))
                await db_session.commit()

    asyncio.run(_run())
