"use client";

import { useState } from "react";
import Link from "next/link";

const SOURCE_TYPES = [
  { value: "file_upload", label: "本地文件上传", desc: "通过界面上传文件，即时校验" },
  { value: "nas", label: "NAS 同步", desc: "挂载共享目录，批量同步" },
  { value: "crawler", label: "Crawler 爬虫", desc: "配置规则，自动抓取 Web 页面" },
  { value: "database", label: "数据库对接", desc: "直连数据库，按表/视图同步" },
  { value: "webhook", label: "API 推送", desc: "通过 Webhook/API 批量提交" },
];

type ConnectorField = {
  key: string;
  label: string;
  placeholder: string;
  type?: string;
  required?: boolean;
  hint?: string;
};

const CONNECTOR_FIELDS: Record<string, ConnectorField[]> = {
  file_upload: [],
  nas: [
    {
      key: "cfg_mount_path",
      label: "挂载路径",
      placeholder: "/mnt/nas/teaching-resources",
      required: true,
    },
    {
      key: "cfg_scan_pattern",
      label: "扫描模式",
      placeholder: "**/*.pdf,**/*.docx",
      hint: "Glob 模式，逗号分隔",
    },
  ],
  crawler: [
    {
      key: "cfg_target_url",
      label: "目标 URL",
      placeholder: "https://example.edu.cn/resources",
      required: true,
    },
    {
      key: "cfg_schedule_cron",
      label: "调度 Cron",
      placeholder: "0 2 * * *",
      hint: "留空则手动触发",
    },
    {
      key: "cfg_auth_token",
      label: "认证 Token",
      placeholder: "Bearer xxx",
      type: "password",
      hint: "如目标需认证",
    },
  ],
  database: [
    {
      key: "cfg_connection_string",
      label: "连接字符串",
      placeholder: "postgresql://user:pass@host:5432/db",
      type: "password",
      required: true,
    },
    {
      key: "cfg_query",
      label: "查询语句",
      placeholder: "SELECT * FROM resources WHERE updated_at > :last_sync",
    },
    {
      key: "cfg_schedule_cron",
      label: "调度 Cron",
      placeholder: "0 */6 * * *",
      hint: "留空则手动触发",
    },
  ],
  webhook: [
    {
      key: "cfg_webhook_secret",
      label: "Webhook Secret",
      placeholder: "whsec_xxx",
      type: "password",
      required: true,
    },
    {
      key: "cfg_allowed_ips",
      label: "允许 IP（逗号分隔）",
      placeholder: "10.0.0.0/8, 192.168.1.0/24",
    },
  ],
};

export function CreateDataSourceForm({
  action,
  preselectedType,
}: {
  action: (formData: FormData) => void;
  preselectedType: string;
}) {
  const [sourceType, setSourceType] = useState(preselectedType || "file_upload");
  const fields = CONNECTOR_FIELDS[sourceType] ?? [];

  return (
    <form action={action}>
      <div style={{ display: "grid", gap: 16 }}>
        <div className="form-group">
          <label>数据源名称 *</label>
          <input name="name" required placeholder="例：教学资源 NAS" className="form-input" />
        </div>

        <div className="form-group">
          <label>编码 *</label>
          <input
            name="code"
            required
            placeholder="例：ds_teaching_nas"
            className="form-input"
            pattern="[a-z0-9_]+"
            title="仅允许小写字母、数字和下划线"
          />
          <span
            style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, display: "block" }}
          >
            唯一标识符，仅允许小写字母、数字和下划线
          </span>
        </div>

        <div className="form-group">
          <label>连接器类型 *</label>
          <select
            name="source_type"
            required
            className="form-select"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
          >
            {SOURCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label} — {t.desc}
              </option>
            ))}
          </select>
        </div>

        {/* ── Connector Config (dynamic) ── */}
        {fields.length > 0 && (
          <fieldset
            style={{
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-lg)",
              padding: 16,
              margin: 0,
            }}
          >
            <legend style={{ fontSize: 13, fontWeight: 600, padding: "0 8px" }}>
              连接器配置 — {SOURCE_TYPES.find((t) => t.value === sourceType)?.label}
            </legend>
            <div style={{ display: "grid", gap: 14, marginTop: 8 }}>
              {fields.map((f) => (
                <div className="form-group" key={f.key}>
                  <label>
                    {f.label}
                    {f.required && (
                      <span style={{ color: "var(--danger-600)", marginLeft: 2 }}>*</span>
                    )}
                  </label>
                  <input
                    name={f.key}
                    placeholder={f.placeholder}
                    type={f.type ?? "text"}
                    required={f.required}
                    className="form-input"
                  />
                  {f.hint && (
                    <span
                      style={{
                        fontSize: 11,
                        color: "var(--text-muted)",
                        marginTop: 4,
                        display: "block",
                      }}
                    >
                      {f.hint}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </fieldset>
        )}

        {fields.length === 0 && sourceType === "file_upload" && (
          <div
            style={{
              padding: "12px 16px",
              borderRadius: "var(--radius-lg)",
              background: "var(--success-bg)",
              border: "1px solid var(--success-100)",
              fontSize: 13,
              color: "var(--success-700)",
            }}
          >
            文件上传类型无需额外连接配置，注册后直接在「数据接入」中上传文件即可。
          </div>
        )}

        <div className="form-group">
          <label>描述</label>
          <textarea
            name="description"
            placeholder="可选：描述此数据源的用途和数据范围"
            className="form-textarea"
            rows={3}
          />
        </div>

        <div className="form-group">
          <label>组织范围提示</label>
          <input
            name="org_scope_hint"
            placeholder="例：教务处, 信息中心（逗号分隔）"
            className="form-input"
          />
          <span
            style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, display: "block" }}
          >
            AI 治理时参考的组织范围提示，逗号分隔多个值
          </span>
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <button
            type="submit"
            style={{
              padding: "10px 24px",
              borderRadius: "var(--radius-lg)",
              background: "var(--brand)",
              color: "#fff",
              fontWeight: 600,
              fontSize: 14,
              border: "none",
              cursor: "pointer",
            }}
          >
            注册数据源
          </button>
          <Link
            href="/data-sources"
            style={{
              padding: "10px 16px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--line)",
              color: "var(--text-secondary)",
              fontSize: 14,
              textDecoration: "none",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            取消
          </Link>
        </div>
      </div>
    </form>
  );
}
