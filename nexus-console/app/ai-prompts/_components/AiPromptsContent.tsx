"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Select,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Eye,
  FlaskConical,
  History,
  RotateCcw,
  Save,
} from "lucide-react";

import { formatTime } from "@/lib/format-time";
import {
  dryRunPromptCandidate,
  fetchPromptHistory,
  saveActivePrompt,
  validatePromptCandidate,
  type PromptCandidateDryRunResult,
  type PromptProfile,
  type PromptProfileCandidate,
} from "@/lib/prompt-profiles-api";
import {
  CORE_PROMPT_SCENARIOS,
  DOMAIN_PROMPT_SCENARIOS,
  findPromptScenario,
  validateScenarioVariables,
  type PromptScenarioDefinition,
} from "@/lib/prompt-scenarios";

type PromptDraft = {
  promptTemplate: string;
  outputSchemaText: string;
  promptVersion: string;
  outputSchemaVersion: string;
  temperature: number;
  redactionPolicy: PromptProfile["redaction_policy"];
};

type EditorValidation = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  contentHash?: string;
};

const EMPTY_DRAFT: PromptDraft = {
  promptTemplate: "",
  outputSchemaText: "{}",
  promptVersion: "",
  outputSchemaVersion: "1.0",
  temperature: 0.2,
  redactionPolicy: "masked_content",
};

const REDACTION_OPTIONS = [
  { value: "metadata_only", label: "仅元数据" },
  { value: "masked_content", label: "脱敏内容" },
  { value: "full_content_private", label: "私有全量内容" },
];

function profileToDraft(profile: PromptProfile | undefined): PromptDraft {
  if (!profile) return EMPTY_DRAFT;
  return {
    promptTemplate: profile.prompt_template ?? "",
    outputSchemaText: JSON.stringify(profile.output_schema ?? {}, null, 2),
    promptVersion: profile.prompt_version ?? "",
    outputSchemaVersion: profile.output_schema_version ?? "1.0",
    temperature: profile.temperature ?? 0.2,
    redactionPolicy: profile.redaction_policy ?? "masked_content",
  };
}

function hasEditableProfileContract(profile: PromptProfile): boolean {
  return (
    typeof profile.prompt_template === "string" &&
    profile.output_schema !== null &&
    !Array.isArray(profile.output_schema) &&
    typeof profile.output_schema === "object" &&
    typeof profile.content_hash === "string"
  );
}

function draftFingerprint(draft: PromptDraft): string {
  return JSON.stringify(draft);
}

function parseOutputSchema(text: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(text);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("输出 Schema 根节点必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

function buildCandidate(
  profile: PromptProfile,
  draft: PromptDraft,
  outputSchema: Record<string, unknown>,
): PromptProfileCandidate {
  return {
    profile_name: profile.profile_name,
    task_type: profile.task_type,
    scenario: profile.scenario,
    prompt_version: draft.promptVersion.trim(),
    prompt_template: draft.promptTemplate,
    output_schema: outputSchema,
    output_schema_version: draft.outputSchemaVersion.trim(),
    scoring_weight_version: profile.scoring_weight_version,
    temperature: draft.temperature,
    redaction_policy: draft.redactionPolicy,
  };
}

function shortHash(hash: string): string {
  if (!hash) return "-";
  return hash.length > 12 ? hash.slice(0, 12) : hash;
}

export default function AiPromptsContent({ profiles }: { profiles: PromptProfile[] }) {
  const { message, modal } = App.useApp();
  const defaultProfileName = CORE_PROMPT_SCENARIOS[0].profileName;
  const [profileState, setProfileState] = useState(profiles);
  const [selectedProfileName, setSelectedProfileName] = useState(defaultProfileName);
  const [domainExpanded, setDomainExpanded] = useState(false);
  const [draft, setDraft] = useState(() =>
    profileToDraft(profiles.find((profile) => profile.profile_name === defaultProfileName)),
  );
  const [validation, setValidation] = useState<EditorValidation | null>(null);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [changeSummary, setChangeSummary] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [history, setHistory] = useState<PromptProfile[]>([]);
  const [historySelection, setHistorySelection] = useState<PromptProfile | null>(null);
  const [dryRunOpen, setDryRunOpen] = useState(false);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [normalizedRefId, setNormalizedRefId] = useState("");
  const [dryRunResult, setDryRunResult] = useState<PromptCandidateDryRunResult | null>(null);

  const profileByName = useMemo(
    () => new Map(profileState.map((profile) => [profile.profile_name, profile])),
    [profileState],
  );
  const selectedProfile = profileByName.get(selectedProfileName);
  const selectedScenario = findPromptScenario(selectedProfileName) ?? CORE_PROMPT_SCENARIOS[0];
  const editableContractAvailable = selectedProfile
    ? hasEditableProfileContract(selectedProfile)
    : false;
  const isDirty = selectedProfile
    ? draftFingerprint(draft) !== draftFingerprint(profileToDraft(selectedProfile))
    : false;

  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const loadScenario = useCallback(
    (profileName: string) => {
      setSelectedProfileName(profileName);
      setDraft(profileToDraft(profileByName.get(profileName)));
      setValidation(null);
      setDryRunResult(null);
    },
    [profileByName],
  );

  function selectScenario(profileName: string) {
    if (profileName === selectedProfileName) return;
    if (!isDirty) {
      loadScenario(profileName);
      return;
    }
    modal.confirm({
      title: "放弃未保存的修改？",
      content: "切换场景后，当前 Prompt 模板和 Schema 的修改将不会保留。",
      okText: "放弃并切换",
      cancelText: "继续编辑",
      okButtonProps: { danger: true },
      onOk: () => loadScenario(profileName),
    });
  }

  function resetDraft() {
    if (!selectedProfile || !isDirty) return;
    modal.confirm({
      title: "重置当前修改？",
      content: "编辑器将恢复为当前生效版本。",
      okText: "重置",
      cancelText: "取消",
      onOk: () => {
        setDraft(profileToDraft(selectedProfile));
        setValidation(null);
      },
    });
  }

  function validateLocally(): Record<string, unknown> | null {
    const errors: string[] = [];
    let schema: Record<string, unknown> | null = null;

    if (!draft.promptTemplate.trim()) errors.push("提示词模板不能为空");
    if (!draft.promptVersion.trim()) errors.push("Prompt 版本不能为空");
    if (!draft.outputSchemaVersion.trim()) errors.push("Schema 版本不能为空");
    errors.push(...validateScenarioVariables(draft.promptTemplate, selectedScenario));
    try {
      schema = parseOutputSchema(draft.outputSchemaText);
    } catch (error) {
      errors.push(error instanceof Error ? error.message : "输出 Schema 不是合法 JSON");
    }

    if (errors.length > 0) {
      setValidation({ valid: false, errors, warnings: [] });
      message.error("校验未通过");
      return null;
    }
    return schema;
  }

  async function runValidation(showSuccess = true): Promise<PromptProfileCandidate | null> {
    if (!selectedProfile) return null;
    const schema = validateLocally();
    if (!schema) return null;
    const candidate = buildCandidate(selectedProfile, draft, schema);

    setValidating(true);
    try {
      const result = await validatePromptCandidate(candidate);
      setValidation({
        valid: result.valid,
        errors: result.errors,
        warnings: result.warnings,
        contentHash: result.content_hash,
      });
      if (result.valid && showSuccess) message.success("Prompt 模板校验通过");
      if (!result.valid) message.error("校验未通过");
      return result.valid ? candidate : null;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setValidation({ valid: false, errors: [detail], warnings: [] });
      message.error(`校验失败：${detail}`);
      return null;
    } finally {
      setValidating(false);
    }
  }

  async function openSaveModal() {
    if (!isDirty || saving) return;
    const candidate = await runValidation(false);
    if (!candidate) return;
    setChangeSummary("");
    setSaveModalOpen(true);
  }

  async function submitSave() {
    if (!selectedProfile || !changeSummary.trim() || saving) return;
    const schema = validateLocally();
    if (!schema) {
      setSaveModalOpen(false);
      return;
    }
    const candidate = buildCandidate(selectedProfile, draft, schema);
    setSaving(true);
    try {
      const updated = await saveActivePrompt(selectedProfile.profile_name, {
        scenario: candidate.scenario,
        prompt_version: candidate.prompt_version,
        prompt_template: candidate.prompt_template,
        output_schema: candidate.output_schema,
        output_schema_version: candidate.output_schema_version,
        scoring_weight_version: candidate.scoring_weight_version,
        temperature: candidate.temperature,
        redaction_policy: candidate.redaction_policy,
        change_summary: changeSummary.trim(),
      });
      setProfileState((current) => [
        ...current.filter((profile) => profile.profile_name !== updated.profile_name),
        updated,
      ]);
      setDraft(profileToDraft(updated));
      setValidation(null);
      setSaveModalOpen(false);
      setChangeSummary("");
      message.success(`已生效为配置版本 v${updated.profile_version}`);
    } catch (error) {
      message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSaving(false);
    }
  }

  async function openHistory() {
    if (!selectedProfile) return;
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistory([]);
    setHistorySelection(null);
    try {
      const versions = await fetchPromptHistory(selectedProfile.profile_name);
      setHistory(versions);
      setHistorySelection(versions[0] ?? null);
    } catch (error) {
      message.error(`历史版本加载失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function openDryRun() {
    const candidate = await runValidation(false);
    if (!candidate) return;
    setNormalizedRefId("");
    setDryRunResult(null);
    setDryRunOpen(true);
  }

  async function submitDryRun() {
    if (!normalizedRefId.trim() || dryRunLoading) return;
    const candidate = await runValidation(false);
    if (!candidate) {
      setDryRunOpen(false);
      return;
    }
    setDryRunLoading(true);
    try {
      const result = await dryRunPromptCandidate(candidate, normalizedRefId.trim());
      setDryRunResult(result);
      message.success("试运行完成，未写入治理结果");
    } catch (error) {
      message.error(`试运行失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setDryRunLoading(false);
    }
  }

  const historyColumns: TableColumnsType<PromptProfile> = [
    {
      title: "配置版本",
      dataIndex: "profile_version",
      width: 96,
      render: (value: number) => `v${value}`,
    },
    { title: "Prompt 版本", dataIndex: "prompt_version", width: 120 },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value: PromptProfile["status"]) => (
        <Tag color={value === "active" ? "success" : "default"}>
          {value === "active" ? "生效中" : value === "archived" ? "已归档" : "已禁用"}
        </Tag>
      ),
    },
    {
      title: "变更摘要",
      dataIndex: "change_summary",
      ellipsis: true,
      render: (value: string | null) => value || "-",
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 145,
      render: (value: string) => formatTime(value).display,
    },
    {
      title: "查看",
      key: "view",
      width: 72,
      render: (_, record) => (
        <Tooltip title="查看只读版本">
          <Button
            type="text"
            icon={<Eye size={16} />}
            aria-label={`查看配置版本 v${record.profile_version}`}
            onClick={() => setHistorySelection(record)}
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <section className="prompt-workspace" aria-label="Prompt 提示词工作区">
      <aside className="prompt-scenario-panel" aria-label="提示词模板场景">
        <div className="prompt-scenario-heading">
          <span>提示词模板</span>
          <span>{CORE_PROMPT_SCENARIOS.length}</span>
        </div>
        <nav className="prompt-scenario-list" aria-label="核心提示词模板">
          {CORE_PROMPT_SCENARIOS.map((scenario) => (
            <ScenarioButton
              key={scenario.profileName}
              scenario={scenario}
              selected={selectedProfileName === scenario.profileName}
              available={profileByName.has(scenario.profileName)}
              onSelect={selectScenario}
            />
          ))}
        </nav>

        <button
          type="button"
          className="prompt-domain-toggle"
          aria-expanded={domainExpanded}
          onClick={() => setDomainExpanded((expanded) => !expanded)}
        >
          <span className="flex items-center gap-2">
            {domainExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            领域场景
          </span>
          <span>{DOMAIN_PROMPT_SCENARIOS.length}</span>
        </button>
        {domainExpanded && (
          <nav className="prompt-scenario-list" aria-label="领域提示词模板">
            {DOMAIN_PROMPT_SCENARIOS.map((scenario) => (
              <ScenarioButton
                key={scenario.profileName}
                scenario={scenario}
                selected={selectedProfileName === scenario.profileName}
                available={profileByName.has(scenario.profileName)}
                onSelect={selectScenario}
              />
            ))}
          </nav>
        )}
      </aside>

      <article className="prompt-editor-panel">
        <header className="prompt-editor-header">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2>{selectedScenario.displayName}</h2>
              {selectedProfile ? <Tag color="success">生效中</Tag> : <Tag>未配置</Tag>}
              {isDirty && <Tag color="warning">未保存</Tag>}
            </div>
            <p>{selectedScenario.description}</p>
          </div>
          {selectedProfile && (
            <dl className="prompt-version-meta">
              <div>
                <dt>配置版本</dt>
                <dd>v{selectedProfile.profile_version}</dd>
              </div>
              <div>
                <dt>Prompt 版本</dt>
                <dd>{selectedProfile.prompt_version}</dd>
              </div>
              <div>
                <dt>更新</dt>
                <dd title={formatTime(selectedProfile.updated_at).iso}>
                  {formatTime(selectedProfile.updated_at).display} ·{" "}
                  {selectedProfile.created_by || "系统"}
                </dd>
              </div>
              <div>
                <dt>内容哈希</dt>
                <dd className="font-mono">{shortHash(selectedProfile.content_hash)}</dd>
              </div>
            </dl>
          )}
        </header>

        {!selectedProfile ? (
          <div className="prompt-empty-state">
            <Empty description="当前环境没有该场景的活动 Prompt 版本" />
          </div>
        ) : (
          <>
            <div className="prompt-document">
              {!editableContractAvailable && (
                <Alert
                  type="error"
                  showIcon
                  title="Prompt 数据契约不完整"
                  description="当前后端未返回模板内容、输出 Schema 或内容哈希。请升级并重启 nexus-api 后再编辑，当前页面已锁定以避免覆盖生效版本。"
                />
              )}
              <section className="prompt-document-section prompt-template-section">
                <div className="prompt-section-label">
                  <label htmlFor="prompt-template-editor">提示词模板</label>
                  <span>Markdown · {draft.promptTemplate.split("\n").length} 行</span>
                </div>
                <textarea
                  id="prompt-template-editor"
                  aria-label="提示词模板内容"
                  value={draft.promptTemplate}
                  disabled={!editableContractAvailable}
                  onChange={(event) => {
                    setDraft((current) => ({ ...current, promptTemplate: event.target.value }));
                    setValidation(null);
                  }}
                  className="prompt-template-editor"
                  spellCheck={false}
                />
              </section>

              <section className="prompt-document-section">
                <div className="prompt-section-label">
                  <span>允许变量</span>
                  <span>运行时契约</span>
                </div>
                <div className="prompt-variable-list">
                  {selectedScenario.allowedVariables.length > 0 ? (
                    selectedScenario.allowedVariables.map((variable) => (
                      <Tag key={variable} color="blue" className="font-mono">
                        {variable}
                      </Tag>
                    ))
                  ) : (
                    <Typography.Text type="secondary">
                      无模板变量，运行时输入通过独立消息提供
                    </Typography.Text>
                  )}
                </div>
              </section>

              <section className="prompt-document-section prompt-schema-section">
                <div className="prompt-section-label">
                  <label htmlFor="prompt-schema-editor">输出 Schema</label>
                  <span>JSON Object</span>
                </div>
                <textarea
                  id="prompt-schema-editor"
                  aria-label="输出 Schema"
                  value={draft.outputSchemaText}
                  disabled={!editableContractAvailable}
                  onChange={(event) => {
                    setDraft((current) => ({ ...current, outputSchemaText: event.target.value }));
                    setValidation(null);
                  }}
                  className="prompt-schema-editor"
                  spellCheck={false}
                />
              </section>

              <section className="prompt-document-section">
                <div className="prompt-section-label">
                  <span>运行参数</span>
                  <span>{selectedScenario.impactText}</span>
                </div>
                <div className="prompt-runtime-grid">
                  <label>
                    <span>Prompt 版本</span>
                    <Input
                      value={draft.promptVersion}
                      disabled={!editableContractAvailable}
                      maxLength={40}
                      onChange={(event) =>
                        setDraft((current) => ({ ...current, promptVersion: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    <span>Schema 版本</span>
                    <Input
                      value={draft.outputSchemaVersion}
                      disabled={!editableContractAvailable}
                      maxLength={40}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          outputSchemaVersion: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label>
                    <span>Temperature</span>
                    <InputNumber
                      min={0}
                      max={2}
                      step={0.1}
                      value={draft.temperature}
                      disabled={!editableContractAvailable}
                      onChange={(value) =>
                        setDraft((current) => ({ ...current, temperature: value ?? 0.2 }))
                      }
                    />
                  </label>
                  <label>
                    <span>脱敏策略</span>
                    <Select
                      value={draft.redactionPolicy}
                      disabled={!editableContractAvailable}
                      options={REDACTION_OPTIONS}
                      onChange={(value: PromptProfile["redaction_policy"]) =>
                        setDraft((current) => ({ ...current, redactionPolicy: value }))
                      }
                    />
                  </label>
                </div>
              </section>

              {validation && (
                <Alert
                  className="prompt-validation-alert"
                  type={validation.valid ? "success" : "error"}
                  showIcon
                  title={validation.valid ? "校验通过" : "校验未通过"}
                  description={
                    <div className="space-y-1">
                      {validation.errors.map((error) => (
                        <div key={error}>{error}</div>
                      ))}
                      {validation.warnings.map((warning) => (
                        <div key={warning}>警告：{warning}</div>
                      ))}
                      {validation.contentHash && (
                        <div className="font-mono text-xs">
                          候选内容哈希：{shortHash(validation.contentHash)}
                        </div>
                      )}
                    </div>
                  }
                />
              )}
            </div>

            <footer className="prompt-action-bar">
              <div>
                <Button icon={<History size={16} />} onClick={openHistory}>
                  历史版本
                </Button>
                <Button icon={<RotateCcw size={16} />} disabled={!isDirty} onClick={resetDraft}>
                  重置
                </Button>
              </div>
              <div>
                <Button
                  icon={<CheckCircle2 size={16} />}
                  loading={validating}
                  disabled={!editableContractAvailable}
                  onClick={() => void runValidation()}
                >
                  校验
                </Button>
                <Tooltip
                  title={
                    selectedScenario.dryRunSupported
                      ? "使用 normalized_asset_ref 执行，不写入治理结果"
                      : "该场景尚未接入候选 Prompt 试运行适配器"
                  }
                >
                  <span>
                    <Button
                      icon={<FlaskConical size={16} />}
                      aria-disabled={
                        !editableContractAvailable || !selectedScenario.dryRunSupported
                      }
                      disabled={
                        !editableContractAvailable || !selectedScenario.dryRunSupported
                      }
                      onClick={() => void openDryRun()}
                    >
                      试运行
                    </Button>
                  </span>
                </Tooltip>
                <Button
                  type="primary"
                  icon={<Save size={16} />}
                  disabled={!editableContractAvailable || !isDirty}
                  loading={saving}
                  onClick={() => void openSaveModal()}
                >
                  保存并生效
                </Button>
              </div>
            </footer>
          </>
        )}
      </article>

      <Modal
        title="保存并生效"
        open={saveModalOpen}
        okText="确认保存并生效"
        cancelText="取消"
        confirmLoading={saving}
        okButtonProps={{ disabled: !changeSummary.trim() }}
        onOk={() => void submitSave()}
        onCancel={() => !saving && setSaveModalOpen(false)}
      >
        <Alert
          className="mb-4"
          type="warning"
          showIcon
          title="保存将创建新的活动版本，并自动归档当前活动版本。"
        />
        <label className="prompt-modal-field" htmlFor="prompt-change-summary">
          <span>变更摘要</span>
          <Input.TextArea
            id="prompt-change-summary"
            value={changeSummary}
            rows={3}
            maxLength={512}
            showCount
            placeholder="说明本次 Prompt 或 Schema 的调整"
            onChange={(event) => setChangeSummary(event.target.value)}
          />
        </label>
      </Modal>

      <Modal
        title={`试运行 · ${selectedScenario.displayName}`}
        open={dryRunOpen}
        width={720}
        okText="执行试运行"
        cancelText="关闭"
        confirmLoading={dryRunLoading}
        okButtonProps={{ disabled: !normalizedRefId.trim() }}
        onOk={() => void submitDryRun()}
        onCancel={() => !dryRunLoading && setDryRunOpen(false)}
      >
        <label className="prompt-modal-field" htmlFor="prompt-dry-run-ref">
          <span>normalized_ref_id</span>
          <Input
            id="prompt-dry-run-ref"
            value={normalizedRefId}
            placeholder="输入标准化资产引用 ID"
            onChange={(event) => setNormalizedRefId(event.target.value)}
          />
        </label>
        {dryRunResult && (
          <div className="prompt-dry-run-result">
            <div className="flex items-center justify-between">
              <strong>运行结果</strong>
              <Tag color="success">未持久化</Tag>
            </div>
            <pre>{JSON.stringify(dryRunResult.output, null, 2)}</pre>
          </div>
        )}
      </Modal>

      <Drawer
        title={`${selectedScenario.displayName} · 历史版本`}
        open={historyOpen}
        size={860}
        onClose={() => setHistoryOpen(false)}
      >
        <Table<PromptProfile>
          rowKey="id"
          size="small"
          loading={historyLoading}
          columns={historyColumns}
          dataSource={history}
          pagination={false}
          rowClassName={(record) =>
            record.id === historySelection?.id ? "prompt-history-row-selected" : ""
          }
        />
        {historySelection && (
          <section className="prompt-history-preview" aria-label="历史版本只读内容">
            <div className="prompt-history-preview-header">
              <div>
                <strong>配置版本 v{historySelection.profile_version}</strong>
                <span>Prompt {historySelection.prompt_version}</span>
              </div>
              <Tag>{historySelection.status === "active" ? "生效中" : "只读"}</Tag>
            </div>
            <h3>提示词模板</h3>
            <pre>{historySelection.prompt_template}</pre>
            <h3>输出 Schema</h3>
            <pre>{JSON.stringify(historySelection.output_schema, null, 2)}</pre>
          </section>
        )}
      </Drawer>
    </section>
  );
}

function ScenarioButton({
  scenario,
  selected,
  available,
  onSelect,
}: {
  scenario: PromptScenarioDefinition;
  selected: boolean;
  available: boolean;
  onSelect: (profileName: string) => void;
}) {
  return (
    <button
      type="button"
      className={["prompt-scenario-button", selected ? "is-selected" : ""]
        .filter(Boolean)
        .join(" ")}
      aria-label={scenario.displayName}
      aria-current={selected ? "page" : undefined}
      onClick={() => onSelect(scenario.profileName)}
    >
      <span>{scenario.displayName}</span>
      <i className={available ? "is-available" : ""} aria-hidden="true" />
    </button>
  );
}
