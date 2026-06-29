import sys
import asyncio

from app.services.email import EmailService


async def main() -> None:
    recipient = sys.argv[1].strip() if len(sys.argv) > 1 else None
    result = await EmailService.send_test_email(recipient)
    print(
        {
            "success": result.success,
            "message": result.message,
            "recipient": result.recipient,
        }
    )


asyncio.run(main())
