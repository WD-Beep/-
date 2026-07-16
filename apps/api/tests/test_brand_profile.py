from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.link_knowledge_base import LinkKnowledgeBase
from app.models.tenant import Product
from app.services.brand_profile import load_brand_profile


def test_brand_profile_uses_english_brand_from_link_knowledge_when_product_name_is_chinese():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db:
            product = Product(
                workspace_id=1,
                name="多莱达",
                brand=None,
                slug=f"duoleda-test-{suffix}",
                is_default=False,
            )
            db.add(product)
            await db.flush()
            base = LinkKnowledgeBase(
                workspace_id=1,
                user_id=1,
                product_id=product.id,
                name=f"EPEDAL24 source {suffix}",
                url="https://example.com/product",
                domain="example.com",
                source_type="url",
                status="parsed",
                extracted_knowledge={"brand_name": "EPEDAL24", "product_name": "Travel Laundry Bag"},
                summary="EPEDAL24 makes travel organizers.",
            )
            db.add(base)
            await db.commit()

            profile = await load_brand_profile(db, product_id=product.id)

            assert profile.brand_name == "EPEDAL24"
            assert profile.signature == "EPEDAL24 Team"
            assert profile.product_links == ["https://example.com/product"]
            assert "Product links: https://example.com/product" in profile.to_prompt_block()

            await db.execute(delete(LinkKnowledgeBase).where(LinkKnowledgeBase.id == base.id))
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.commit()

    asyncio.run(_run())
