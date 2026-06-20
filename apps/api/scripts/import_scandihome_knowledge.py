"""导入 ScandiHome 品牌资料到默认产品知识库。

用法（在 apps/api 目录下）：
  python -m scripts.import_scandihome_knowledge

可选环境变量：
  SCANDIHOME_PDF_PATH
  SCANDIHOME_PPTX_PATH
  IMPORT_PRODUCT_ID（默认使用 is_default=true 的产品）
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session_factory
from app.deps.tenant import TenantContext
from app.models.tenant import Product
from app.services.knowledge.knowledge_service import KnowledgeService

DEFAULT_PDF = Path(r"C:\Users\Administrator\Desktop\ScandiHome_视觉手册_v1_2.pdf")
DEFAULT_PPTX = Path(r"C:\Users\Administrator\Desktop\ScandiHome 2026 视觉升级 PPT新.pptx")


async def _resolve_product_id(db) -> int:
    override = os.getenv("IMPORT_PRODUCT_ID", "").strip()
    if override.isdigit():
        return int(override)
    result = await db.execute(
        select(Product).where(Product.is_default.is_(True)).order_by(Product.id.asc()).limit(1)
    )
    product = result.scalar_one_or_none()
    if not product:
        result = await db.execute(select(Product).order_by(Product.id.asc()).limit(1))
        product = result.scalar_one_or_none()
    if not product:
        raise RuntimeError("数据库中无可用产品，请先创建默认产品/品牌")
    return product.id


async def main() -> None:
    pdf_path = Path(os.getenv("SCANDIHOME_PDF_PATH", str(DEFAULT_PDF))).expanduser()
    pptx_path = Path(os.getenv("SCANDIHOME_PPTX_PATH", str(DEFAULT_PPTX))).expanduser()

    missing = [str(p) for p in (pdf_path, pptx_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"以下文件不存在：{', '.join(missing)}")

    async with async_session_factory() as db:
        product_id = await _resolve_product_id(db)
        product = await db.get(Product, product_id)
        if not product:
            raise RuntimeError(f"产品 {product_id} 不存在")

        ctx = TenantContext(
            user_id=1,
            product_id=product_id,
            workspace_id=product.workspace_id,
            is_admin=True,
        )
        base = await KnowledgeService.get_or_create_default_base(db, ctx=ctx, product_id=product_id)
        print(f"目标产品 ID={product_id}，知识库 ID={base.id} ({base.name})")

        for file_path in (pdf_path, pptx_path):
            print(f"导入: {file_path}")
            doc = await KnowledgeService.create_document_from_path(
                db,
                ctx=ctx,
                product_id=product_id,
                file_path=str(file_path),
                knowledge_base_id=base.id,
                is_upload=False,
            )
            print(f"  -> 文档 ID={doc.id}, 状态={doc.status}, 片段数={doc.chunk_count}")

    print("ScandiHome 品牌资料导入完成。")


if __name__ == "__main__":
    asyncio.run(main())
