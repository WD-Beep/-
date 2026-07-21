# 文件说明：后端接口数据结构，定义请求和响应字段；当前文件：tenant
from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampMixin


class ProductRead(ORMModel, TimestampMixin):
    id: int
    workspace_id: int
    name: str
    slug: str
    brand: str | None = None
    description: str | None = None
    is_default: bool = False
    is_archived: bool = False
    is_hidden: bool = False
    is_test: bool = False
    created_source: str | None = None
    display_order: int | None = None


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_default: bool = False


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_default: bool | None = None
    is_hidden: bool | None = None
    is_archived: bool | None = None


class UserRead(ORMModel, TimestampMixin):
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    is_active: bool = True
    is_admin: bool = False
