"""安全标记历史测试产品（不删除记录）。

用法:
    cd apps/api
    python -m scripts.mark_test_products --dry-run
    python -m scripts.mark_test_products --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.tenant import Product
from app.services.product_visibility import looks_like_test_product


async def _run(*, apply: bool) -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(select(Product).order_by(Product.id.asc()))).scalars().all()
        candidates: list[Product] = []
        for row in rows:
            if row.is_test and row.is_hidden:
                continue
            if looks_like_test_product(name=row.name, slug=row.slug, brand=row.brand):
                candidates.append(row)

        print(f"扫描产品: {len(rows)}，待标记测试: {len(candidates)}")
        for row in candidates:
            print(f"  - id={row.id} slug={row.slug} name={row.name}")

        if not apply:
            print("dry-run 模式，未写入数据库。加 --apply 执行标记。")
            return

        for row in candidates:
            row.is_test = True
            row.is_hidden = True
            if not row.created_source:
                row.created_source = "auto_test"
        await db.commit()
        print(f"已标记 {len(candidates)} 条测试产品。")


def main() -> None:
    parser = argparse.ArgumentParser(description="标记测试/临时产品为 hidden + is_test")
    parser.add_argument("--apply", action="store_true", help="写入数据库（默认 dry-run）")
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
