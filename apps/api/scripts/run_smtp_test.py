# 文件说明：后端维护脚本，用于检查、迁移、验证或批处理任务；当前文件：run smtp test
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
