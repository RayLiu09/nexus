import { PageScaffold } from "@/components/PageScaffold";

export default function AiPromptsPage() {
  return (
    <PageScaffold
      title="AI Prompt 配置"
      prototypeId="NX-13"
      summary="维护 AI 治理和质量评分使用的 Prompt 配置，引用既有 LiteLLM 模型别名，不管理模型供应商、密钥或路由规则。"
      columns={["名称", "任务类型", "当前版本", "模型别名", "脱敏策略", "状态", "操作"]}
      statuses={["draft", "validating", "published", "active", "validation_failed", "disabled", "archived"]}
      primaryAction="新建配置"
    />
  );
}
