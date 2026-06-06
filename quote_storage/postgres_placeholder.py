"""PostgreSQL 实现见 ``postgres_impl.py``（由 ``quote_upload_storage`` 按环境加载）。

环境变量：
- QUOTE_DB_BACKEND=postgres
- QUOTE_DATABASE_URL：例 postgresql://用户:密码@主机:端口/数据库

上传文件仍落在项目目录 ``data/uploads/``（与 SQLite 一致）。
"""
