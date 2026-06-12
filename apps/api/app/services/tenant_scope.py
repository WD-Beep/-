"""多产品数据范围：0 表示查看全部产品汇总。"""

ALL_PRODUCTS_ID = 0


def scoped_product_id(product_id: int) -> int | None:
    if product_id == ALL_PRODUCTS_ID:
        return None
    return product_id
