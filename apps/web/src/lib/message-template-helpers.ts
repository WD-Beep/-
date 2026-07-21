// 文件说明：前端公共工具和业务辅助函数；当前文件：message template helpers
import type { MessageTemplate } from "./api.ts";

export function canEditMessageTemplate(template: Pick<MessageTemplate, "is_system_default">): boolean {
  void template;
  return true;
}

export function canDeleteMessageTemplate(template: Pick<MessageTemplate, "is_system_default">): boolean {
  return !template.is_system_default;
}
