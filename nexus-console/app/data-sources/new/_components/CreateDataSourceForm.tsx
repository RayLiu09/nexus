"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Alert, Button, Descriptions, Form, Input, Space, Steps, Tag } from "antd";
import { CheckCircleOutlined, LeftOutlined, RightOutlined } from "@ant-design/icons";

import { CronPicker } from "./CronPicker";

// ── Types ─────────────────────────────────────────────────────────────────

type SourceTypeValue = "file_upload" | "nas" | "crawler" | "database" | "webhook";

interface SourceTypeOption {
  value: SourceTypeValue;
  label: string;
  icon: string;
  desc: string;
  scenario: string;
}

const SOURCE_TYPES: SourceTypeOption[] = [
  {
    value: "file_upload",
    label: "本地文件上传",
    icon: "📤",
    desc: "通过界面拖拽上传文件",
    scenario: "适合临时一次性导入的合同、报告、数据集",
  },
  {
    value: "nas",
    label: "NAS 同步",
    icon: "📡",
    desc: "挂载共享目录，批量同步",
    scenario: "适合教务、行政等组织内固定共享盘",
  },
  {
    value: "crawler",
    label: "Crawler 爬虫",
    icon: "🕷",
    desc: "按规则抓取 Web 页面",
    scenario: "适合定期抓取公告、政策、外部知识库",
  },
  {
    value: "database",
    label: "数据库对接",
    icon: "🗄",
    desc: "直连数据库按查询同步",
    scenario: "适合从结构化业务系统增量同步记录",
  },
  {
    value: "webhook",
    label: "API 推送",
    icon: "⚡",
    desc: "Webhook / API 批量提交",
    scenario: "适合由第三方系统主动推送数据",
  },
];

interface WizardState {
  sourceType: SourceTypeValue;
  name: string;
  code: string;
  description: string;
  orgScopeHint: string;
  cfgMountPath: string;
  cfgScanPattern: string;
  cfgTargetUrl: string;
  cfgScheduleCron: string;
  cfgAuthToken: string;
  cfgConnectionString: string;
  cfgQuery: string;
  cfgWebhookSecret: string;
  cfgAllowedIps: string;
}

const INITIAL_STATE: WizardState = {
  sourceType: "file_upload",
  name: "",
  code: "",
  description: "",
  orgScopeHint: "",
  cfgMountPath: "",
  cfgScanPattern: "",
  cfgTargetUrl: "",
  cfgScheduleCron: "",
  cfgAuthToken: "",
  cfgConnectionString: "",
  cfgQuery: "",
  cfgWebhookSecret: "",
  cfgAllowedIps: "",
};

// ── Helpers ───────────────────────────────────────────────────────────────

function hasConnectionConfig(type: SourceTypeValue): boolean {
  return type !== "file_upload";
}

function validateBasics(state: WizardState): string | null {
  if (!state.name.trim()) return "请填写数据源名称";
  if (!/^[a-z0-9_]+$/.test(state.code)) return "编码仅允许小写字母、数字和下划线";
  return null;
}

function validateConnection(state: WizardState): string | null {
  switch (state.sourceType) {
    case "file_upload":
      return null;
    case "nas":
      if (!state.cfgMountPath.trim()) return "挂载路径必填";
      return null;
    case "crawler":
      if (!state.cfgTargetUrl.trim()) return "目标 URL 必填";
      try {
        new URL(state.cfgTargetUrl);
      } catch {
        return "目标 URL 格式不合法";
      }
      return null;
    case "database":
      if (!state.cfgConnectionString.trim()) return "连接字符串必填";
      return null;
    case "webhook":
      if (!state.cfgWebhookSecret.trim()) return "Webhook Secret 必填";
      return null;
    default:
      return null;
  }
}

// ── Wizard ────────────────────────────────────────────────────────────────

interface CreateDataSourceFormProps {
  action: (formData: FormData) => void;
  preselectedType: string;
}

export function CreateDataSourceForm({ action, preselectedType }: CreateDataSourceFormProps) {
  const validPreselected = SOURCE_TYPES.some((t) => t.value === preselectedType)
    ? (preselectedType as SourceTypeValue)
    : null;

  const [state, setState] = useState<WizardState>(() => ({
    ...INITIAL_STATE,
    sourceType: validPreselected ?? "file_upload",
  }));
  const [step, setStep] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  // file_upload 类型跳过 "连接配置" 步骤
  const totalSteps = hasConnectionConfig(state.sourceType) ? 4 : 3;
  const stepTitles = hasConnectionConfig(state.sourceType)
    ? ["选类型", "基础信息", "连接配置", "确认"]
    : ["选类型", "基础信息", "确认"];

  const update = <K extends keyof WizardState>(key: K, value: WizardState[K]) => {
    setState((prev) => ({ ...prev, [key]: value }));
    setError(null);
  };

  const goNext = () => {
    let err: string | null = null;
    if (step === 0 && !state.sourceType) err = "请选择数据源类型";
    if (step === 1) err = validateBasics(state);
    if (step === 2 && hasConnectionConfig(state.sourceType)) err = validateConnection(state);
    if (err) {
      setError(err);
      return;
    }
    setStep((s) => Math.min(s + 1, totalSteps - 1));
  };

  const goBack = () => {
    setError(null);
    setStep((s) => Math.max(s - 1, 0));
  };

  const typeMeta = useMemo(
    () => SOURCE_TYPES.find((t) => t.value === state.sourceType),
    [state.sourceType],
  );

  const isFinalStep = step === totalSteps - 1;
  const isConfigStep = step === 2 && hasConnectionConfig(state.sourceType);

  return (
    <form action={action} className="grid gap-5">
      {/* 隐藏字段：把 React 状态映射到 server action 期望的 FormData 字段 */}
      <input type="hidden" name="source_type" value={state.sourceType} />
      <input type="hidden" name="name" value={state.name} />
      <input type="hidden" name="code" value={state.code} />
      <input type="hidden" name="description" value={state.description} />
      <input type="hidden" name="org_scope_hint" value={state.orgScopeHint} />
      {state.sourceType === "nas" && (
        <>
          <input type="hidden" name="cfg_mount_path" value={state.cfgMountPath} />
          <input type="hidden" name="cfg_scan_pattern" value={state.cfgScanPattern} />
        </>
      )}
      {state.sourceType === "crawler" && (
        <>
          <input type="hidden" name="cfg_target_url" value={state.cfgTargetUrl} />
          <input type="hidden" name="cfg_schedule_cron" value={state.cfgScheduleCron} />
          <input type="hidden" name="cfg_auth_token" value={state.cfgAuthToken} />
        </>
      )}
      {state.sourceType === "database" && (
        <>
          <input type="hidden" name="cfg_connection_string" value={state.cfgConnectionString} />
          <input type="hidden" name="cfg_query" value={state.cfgQuery} />
          <input type="hidden" name="cfg_schedule_cron" value={state.cfgScheduleCron} />
        </>
      )}
      {state.sourceType === "webhook" && (
        <>
          <input type="hidden" name="cfg_webhook_secret" value={state.cfgWebhookSecret} />
          <input type="hidden" name="cfg_allowed_ips" value={state.cfgAllowedIps} />
        </>
      )}

      <Steps current={step} size="small" items={stepTitles.map((title) => ({ title }))} />

      {error && <Alert type="error" showIcon title={error} />}

      {/* ── Step 0: Type ── */}
      {step === 0 && (
        <div className="grid gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SOURCE_TYPES.map((t) => {
              const selected = state.sourceType === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => update("sourceType", t.value)}
                  className={[
                    "border-line bg-surface flex h-full flex-col gap-2 rounded-xl border p-4 text-left transition-colors",
                    selected
                      ? "border-brand bg-brand-50 ring-brand-200 ring-2"
                      : "hover:border-brand-200 hover:bg-bg-alt",
                  ].join(" ")}
                >
                  <div className="text-2xl">{t.icon}</div>
                  <div className="text-sm font-semibold">{t.label}</div>
                  <div className="text-text-secondary text-xs">{t.desc}</div>
                  <div className="text-text-muted mt-auto text-xs">{t.scenario}</div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Step 1: Basics ── */}
      {step === 1 && (
        <Form layout="vertical" component="div">
          <Form.Item label="数据源名称" required>
            <Input
              value={state.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="例：教学资源 NAS"
            />
          </Form.Item>
          <Form.Item
            label="编码"
            required
            extra="唯一标识符，注册后不可修改；仅允许小写字母、数字和下划线"
          >
            <Input
              value={state.code}
              onChange={(e) => update("code", e.target.value)}
              placeholder="例：ds_teaching_nas"
            />
          </Form.Item>
          <Form.Item label="描述">
            <Input.TextArea
              rows={3}
              value={state.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="可选：描述此数据源的用途和数据范围"
            />
          </Form.Item>
          <Form.Item label="组织范围提示" extra="AI 治理时参考的组织范围提示，逗号分隔多个值">
            <Input
              value={state.orgScopeHint}
              onChange={(e) => update("orgScopeHint", e.target.value)}
              placeholder="例：教务处, 信息中心"
            />
          </Form.Item>
        </Form>
      )}

      {/* ── Step 2: Connection Config ── */}
      {isConfigStep && (
        <Form layout="vertical" component="div">
          {state.sourceType === "nas" && (
            <>
              <Form.Item label="挂载路径" required>
                <Input
                  value={state.cfgMountPath}
                  onChange={(e) => update("cfgMountPath", e.target.value)}
                  placeholder="/mnt/nas/teaching-resources"
                />
              </Form.Item>
              <Form.Item label="扫描模式" extra="Glob 模式，逗号分隔">
                <Input
                  value={state.cfgScanPattern}
                  onChange={(e) => update("cfgScanPattern", e.target.value)}
                  placeholder="**/*.pdf,**/*.docx"
                />
              </Form.Item>
            </>
          )}
          {state.sourceType === "crawler" && (
            <>
              <Form.Item label="目标 URL" required>
                <Input
                  value={state.cfgTargetUrl}
                  onChange={(e) => update("cfgTargetUrl", e.target.value)}
                  placeholder="https://example.edu.cn/resources"
                />
              </Form.Item>
              <Form.Item label="调度计划">
                <CronPicker
                  value={state.cfgScheduleCron}
                  onChange={(c) => update("cfgScheduleCron", c)}
                />
              </Form.Item>
              <Form.Item label="认证 Token" extra="如目标需认证则填写">
                <Input.Password
                  value={state.cfgAuthToken}
                  onChange={(e) => update("cfgAuthToken", e.target.value)}
                  placeholder="Bearer xxx"
                />
              </Form.Item>
            </>
          )}
          {state.sourceType === "database" && (
            <>
              <Form.Item label="连接字符串" required>
                <Input.Password
                  value={state.cfgConnectionString}
                  onChange={(e) => update("cfgConnectionString", e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/db"
                />
              </Form.Item>
              <Form.Item label="查询语句">
                <Input.TextArea
                  rows={3}
                  value={state.cfgQuery}
                  onChange={(e) => update("cfgQuery", e.target.value)}
                  placeholder="SELECT * FROM resources WHERE updated_at > :last_sync"
                />
              </Form.Item>
              <Form.Item label="调度计划">
                <CronPicker
                  value={state.cfgScheduleCron}
                  onChange={(c) => update("cfgScheduleCron", c)}
                />
              </Form.Item>
            </>
          )}
          {state.sourceType === "webhook" && (
            <>
              <Form.Item label="Webhook Secret" required>
                <Input.Password
                  value={state.cfgWebhookSecret}
                  onChange={(e) => update("cfgWebhookSecret", e.target.value)}
                  placeholder="whsec_xxx"
                />
              </Form.Item>
              <Form.Item label="允许 IP（逗号分隔）">
                <Input
                  value={state.cfgAllowedIps}
                  onChange={(e) => update("cfgAllowedIps", e.target.value)}
                  placeholder="10.0.0.0/8, 192.168.1.0/24"
                />
              </Form.Item>
            </>
          )}
        </Form>
      )}

      {/* ── Final step: Review ── */}
      {isFinalStep && (
        <div className="grid gap-4">
          <Alert
            type="info"
            showIcon
            title="确认后将创建数据源"
            description="编码不可修改。其他字段可在数据源详情页编辑。"
          />
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="类型">
              <Space>
                <span className="text-base">{typeMeta?.icon}</span>
                <Tag color="blue">{typeMeta?.label}</Tag>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="名称">{state.name}</Descriptions.Item>
            <Descriptions.Item label="编码">
              <code className="font-mono text-xs">{state.code}</code>
            </Descriptions.Item>
            {state.description && (
              <Descriptions.Item label="描述">{state.description}</Descriptions.Item>
            )}
            {state.orgScopeHint && (
              <Descriptions.Item label="组织范围">{state.orgScopeHint}</Descriptions.Item>
            )}
            {state.sourceType === "nas" && (
              <>
                <Descriptions.Item label="挂载路径">
                  <code className="font-mono text-xs">{state.cfgMountPath}</code>
                </Descriptions.Item>
                {state.cfgScanPattern && (
                  <Descriptions.Item label="扫描模式">
                    <code className="font-mono text-xs">{state.cfgScanPattern}</code>
                  </Descriptions.Item>
                )}
              </>
            )}
            {state.sourceType === "crawler" && (
              <>
                <Descriptions.Item label="目标 URL">
                  <code className="font-mono text-xs">{state.cfgTargetUrl}</code>
                </Descriptions.Item>
                <Descriptions.Item label="调度计划">
                  {state.cfgScheduleCron ? (
                    <code className="font-mono text-xs">{state.cfgScheduleCron}</code>
                  ) : (
                    <span className="text-text-muted text-xs">不定时（仅手动触发）</span>
                  )}
                </Descriptions.Item>
                {state.cfgAuthToken && (
                  <Descriptions.Item label="认证 Token">
                    <Tag color="orange">已设置</Tag>
                  </Descriptions.Item>
                )}
              </>
            )}
            {state.sourceType === "database" && (
              <>
                <Descriptions.Item label="连接字符串">
                  <Tag color="orange">已设置</Tag>
                </Descriptions.Item>
                {state.cfgQuery && (
                  <Descriptions.Item label="查询">
                    <code className="font-mono text-xs">{state.cfgQuery}</code>
                  </Descriptions.Item>
                )}
                <Descriptions.Item label="调度计划">
                  {state.cfgScheduleCron ? (
                    <code className="font-mono text-xs">{state.cfgScheduleCron}</code>
                  ) : (
                    <span className="text-text-muted text-xs">不定时（仅手动触发）</span>
                  )}
                </Descriptions.Item>
              </>
            )}
            {state.sourceType === "webhook" && (
              <>
                <Descriptions.Item label="Webhook Secret">
                  <Tag color="orange">已设置</Tag>
                </Descriptions.Item>
                {state.cfgAllowedIps && (
                  <Descriptions.Item label="允许 IP">{state.cfgAllowedIps}</Descriptions.Item>
                )}
              </>
            )}
          </Descriptions>
        </div>
      )}

      {/* ── Footer actions ── */}
      <div className="border-line-light flex items-center justify-between border-t pt-4">
        <div>
          {step > 0 && (
            <Button onClick={goBack} icon={<LeftOutlined />}>
              上一步
            </Button>
          )}
        </div>
        <Space>
          <Link href="/data-sources">
            <Button type="text">取消</Button>
          </Link>
          {isFinalStep ? (
            <Button type="primary" htmlType="submit" icon={<CheckCircleOutlined />}>
              确认创建
            </Button>
          ) : (
            <Button type="primary" onClick={goNext} icon={<RightOutlined />} iconPlacement="end">
              下一步
            </Button>
          )}
        </Space>
      </div>
    </form>
  );
}
