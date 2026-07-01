from fastapi import APIRouter

from . import ai, collection_tasks, dashboard, email, email_inbound, email_logs, influencers, knowledge, link_import, link_knowledge_bases, message_templates, outreach_campaigns, outreach_records, outreach_send_queue, settings, tenant

api_router = APIRouter(prefix="/api")

api_router.include_router(dashboard.router)
api_router.include_router(influencers.router)
api_router.include_router(collection_tasks.router)
api_router.include_router(link_import.router)
api_router.include_router(link_knowledge_bases.router)
api_router.include_router(email_logs.router)
api_router.include_router(message_templates.router)
api_router.include_router(outreach_send_queue.router)
api_router.include_router(outreach_campaigns.router)
api_router.include_router(outreach_records.router)
api_router.include_router(knowledge.router)
api_router.include_router(email.router)
api_router.include_router(email_inbound.router)
api_router.include_router(email_inbound.email_replies_router)
api_router.include_router(ai.router)
api_router.include_router(settings.router)
api_router.include_router(tenant.router)
