# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：tenant scope
"""多产品数据范围：0 表示查看全部产品汇总。"""

ALL_PRODUCTS_ID = 0


def scoped_product_id(product_id: int) -> int | None:
    if product_id == ALL_PRODUCTS_ID:
        return None
    return product_id
