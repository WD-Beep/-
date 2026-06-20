import asyncio

from app.services.email import EmailService


async def main() -> None:
    result = await EmailService.send_test_email()
    print(
        {
            "success": result.success,
            "message": result.message,
            "recipient": result.recipient,
        }
    )


asyncio.run(main())
