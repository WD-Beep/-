from fastapi import APIRouter

from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.schemas.email import EmailTestRequest, EmailTestResponse, SmtpStatus
from app.services.email import EmailNotConfiguredError, EmailService

router = APIRouter(prefix="/email", tags=["email"])


@router.get("/status", response_model=SmtpStatus)
async def get_smtp_status() -> SmtpStatus:
    return EmailService.get_smtp_status()


@router.post("/test", response_model=EmailTestResponse)
async def send_test_email(payload: EmailTestRequest) -> EmailTestResponse:
    try:
        return await EmailService.send_test_email(
            recipient=str(payload.recipient) if payload.recipient else None,
        )
    except EmailNotConfiguredError:
        return EmailTestResponse(success=False, message=SMTP_NOT_CONFIGURED_MSG)
