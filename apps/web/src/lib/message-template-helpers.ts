import type { MessageTemplate } from "./api.ts";

export function canEditMessageTemplate(template: Pick<MessageTemplate, "is_system_default">): boolean {
  void template;
  return true;
}

export function canDeleteMessageTemplate(template: Pick<MessageTemplate, "is_system_default">): boolean {
  return !template.is_system_default;
}
