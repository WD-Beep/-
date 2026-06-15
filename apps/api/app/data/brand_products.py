"""默认工作区下的真实品牌/产品 seed 数据。"""

from __future__ import annotations

from typing import TypedDict


class BrandProductSeed(TypedDict):
    name: str
    brand: str
    slug: str


DEFAULT_WORKSPACE_ID = 1

# 主体名称 · 品牌名（name · brand）
BRAND_PRODUCT_SEEDS: tuple[BrandProductSeed, ...] = (
    {"name": "珺临", "brand": "EPEDAL24", "slug": "junlin-epedal24"},
    {"name": "哆莱威", "brand": "Aquorix", "slug": "duolaiwei-aquorix"},
    {"name": "哆莱瑞", "brand": "RecoverJoy", "slug": "duolairui-recoverjoy"},
    {"name": "钱钰", "brand": "Scandihome", "slug": "qianyu-scandihome"},
    {"name": "多莱达", "brand": "ACESTRIKE", "slug": "duolaida-acestrike"},
    {"name": "哆莱瑞", "brand": "JourCraf", "slug": "duolairui-jourcraf"},
    {"name": "栢博", "brand": "P.travel", "slug": "baibo-p-travel"},
    {"name": "OCE", "brand": "OCE GEAR", "slug": "oce-oce-gear"},
    {"name": "珺钰", "brand": "P.TRAVEL DESIGN", "slug": "junyu-p-travel-design"},
    {"name": "多莱吉", "brand": "HOMEHIVE", "slug": "duolaiji-homehive"},
    {"name": "玖钰", "brand": "BBCREAT", "slug": "jiuyu-bbcreat"},
)


def format_brand_product_label(name: str, brand: str | None = None) -> str:
    text = (name or "").strip()
    brand_text = (brand or "").strip()
    if text and brand_text:
        return f"{text} · {brand_text}"
    return text or brand_text
