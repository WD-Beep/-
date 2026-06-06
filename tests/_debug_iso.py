import uuid
from test_db_isolation import mount_isolated_quote_db, restore_quote_db, cleanup_isolated_quote_db
from quote_upload_storage import (
    save_quote_calculation,
    update_saved_quote_approval,
    get_saved_quote_approval_for_sales_user,
    get_my_quote_session_detail,
)
from wecom_auth import format_wecom_sales_user_id

root, saved = mount_isolated_quote_db()
sales_a = format_wecom_sales_user_id("UserA")
sales_b = format_wecom_sales_user_id("UserB")
series_uid = f"iso-appr-{uuid.uuid4().hex[:8]}"
calc_id = f"calc-appr-{uuid.uuid4().hex[:8]}"
print("mount ok")
save_quote_calculation(
    quote_uid=series_uid,
    calc_quote_id=calc_id,
    sheet_original_display_name="a.xlsx",
    uploaded_sheet=None,
    quote_result={
        "quote_id": calc_id,
        "product_name": "x",
        "material_total": 1.0,
        "tiers": [{"cost_before_margin": 1.0}],
        "detail_rows": [],
    },
    sales_user_id=sales_a,
    sales_user_name="张三",
)
print("saved")
update_saved_quote_approval(
    series_uid,
    approval_status="approved",
    approval_note="通过",
    reviewed_by="admin-test",
)
print("approved")
print("snap_a", get_saved_quote_approval_for_sales_user(series_uid, sales_a))
print("snap_b", get_saved_quote_approval_for_sales_user(series_uid, sales_b))
print("detail a", get_my_quote_session_detail(series_uid, sales_a) is not None)
print("detail b", get_my_quote_session_detail(series_uid, sales_b))
restore_quote_db(saved)
cleanup_isolated_quote_db(root)
print("done")
