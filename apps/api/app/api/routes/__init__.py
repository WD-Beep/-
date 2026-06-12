from fastapi import APIRouter

from . import ai, collection_tasks, dashboard, email, email_logs, influencers, link_import, message_templates, settings, tenant

api_router = APIRouter(prefix="/api")

api_router.include_router(dashboard.router)
api_router.include_router(influencers.router)
api_router.include_router(collection_tasks.router)
api_router.include_router(link_import.router)
api_router.include_router(email_logs.router)
api_router.include_router(message_templates.router)
api_router.include_router(email.router)
api_router.include_router(ai.router)
api_router.include_router(settings.router)
api_router.include_router(tenant.router)
