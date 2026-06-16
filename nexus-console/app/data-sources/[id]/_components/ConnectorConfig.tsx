"use client";

import { useState } from "react";
import { Button, Drawer, Input, App, Descriptions, Tag } from "antd";
import { EditOutlined } from "@ant-design/icons";
import { patchApiData, type DataSource } from "@/lib/api";

type ConnectorField = {
  key: string;
  label: string;
  placeholder: string;
  required?: boolean;
  sensitive?: boolean;
};

const CONNECTOR_FIELDS: Record<string, ConnectorField[]> = {
  nas: [
    {
      key: "mount_path",
      label: "挂载路径",
      placeholder: "/mnt/nas/teaching-resources",
      required: true,
    },
    { key: "scan_pattern", label: "扫描模式", placeholder: "**/*.pdf,**/*.docx" },
  ],
  crawler: [
    {
      key: "target_url",
      label: "目标 URL",
      placeholder: "https://example.edu.cn/resources",
      required: true,
    },
    { key: "schedule_cron", label: "调度 Cron", placeholder: "0 2 * * *" },
    { key: "auth_token", label: "认证 Token", placeholder: "Bearer xxx", sensitive: true },
  ],
  database: [
    {
      key: "connection_string",
      label: "连接字符串",
      placeholder: "postgresql://user:pass@host:5432/db",
      required: true,
      sensitive: true,
    },
    {
      key: "query",
      label: "查询语句",
      placeholder: "SELECT * FROM resources WHERE updated_at > :last_sync",
    },
    { key: "schedule_cron", label: "调度 Cron", placeholder: "0 */6 * * *" },
  ],
  webhook: [
    {
      key: "webhook_secret",
      label: "Webhook Secret",
      placeholder: "whsec_xxx",
      required: true,
      sensitive: true,
    },
    { key: "allowed_ips", label: "允许 IP（逗号分隔）", placeholder: "10.0.0.0/8, 192.168.1.0/24" },
  ],
  file_upload: [],
};

// PLACEHOLDER_COMPONENT

const SOURCE_TYPE_LABELS: Record<string, string> = {
  file_upload: "本地文件上传",
  nas: "NAS 同步",
  crawler: "Crawler 爬虫",
  database: "数据库对接",
  webhook: "API 推送",
};

function maskSensitive(value: string): string {
  if (!value || value.length < 8) return "••••••••";
  return value.slice(0, 4) + "••••" + value.slice(-4);
}

export function ConnectorConfig({ dataSource }: { dataSource: DataSource }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [showSensitive, setShowSensitive] = useState(false);
  const { message } = App.useApp();

  const fields = CONNECTOR_FIELDS[dataSource.source_type] ?? [];
  const config = dataSource.connection_config ?? {};

  const openEdit = () => {
    const initial: Record<string, string> = {};
    for (const f of fields) {
      initial[f.key] = String(config[f.key] ?? "");
    }
    setFormValues(initial);
    setDrawerOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of fields) {
        const val = formValues[f.key]?.trim();
        if (f.key === "allowed_ips" && val) {
          payload[f.key] = val.split(",").map((s) => s.trim());
        } else if (val) {
          payload[f.key] = val;
        }
      }
      await patchApiData(
        `/api/data-sources/${dataSource.id}`,
        { connection_config: payload },
      );
      message.success("连接器配置已保存");
      setDrawerOpen(false);
      window.location.reload();
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  if (fields.length === 0) {
    return (
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-xl)",
          padding: 20,
          marginBottom: 20,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>连接器配置</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
              {SOURCE_TYPE_LABELS[dataSource.source_type]}{" "}
              类型无需额外连接配置，直接通过界面上传文件即可。
            </div>
          </div>
          <Tag color="green">无需配置</Tag>
        </div>
      </div>
    );
  }

  const hasConfig = Object.keys(config).length > 0;

  return (
    <>
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-xl)",
          padding: 20,
          marginBottom: 20,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: hasConfig ? 16 : 0,
          }}
        >
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>连接器配置</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
              {SOURCE_TYPE_LABELS[dataSource.source_type]} 连接参数
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {hasConfig && (
              <Button size="small" onClick={() => setShowSensitive(!showSensitive)}>
                {showSensitive ? "隐藏敏感值" : "显示敏感值"}
              </Button>
            )}
            <Button size="small" type="primary" icon={<EditOutlined />} onClick={openEdit}>
              {hasConfig ? "编辑配置" : "配置连接器"}
            </Button>
          </div>
        </div>

        {hasConfig ? (
          <Descriptions column={1} size="small" bordered>
            {fields.map((f) => {
              const val = config[f.key];
              let displayVal: string;
              if (val == null || val === "") {
                displayVal = "-";
              } else if (f.sensitive && !showSensitive) {
                displayVal = maskSensitive(String(val));
              } else if (Array.isArray(val)) {
                displayVal = val.join(", ");
              } else {
                displayVal = String(val);
              }
              return (
                <Descriptions.Item
                  key={f.key}
                  label={
                    <span>
                      {f.label}
                      {f.required && (
                        <span style={{ color: "var(--danger-600)", marginLeft: 2 }}>*</span>
                      )}
                      {f.sensitive && (
                        <Tag color="orange" style={{ marginLeft: 6, fontSize: 10 }}>
                          敏感
                        </Tag>
                      )}
                    </span>
                  }
                >
                  <code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{displayVal}</code>
                </Descriptions.Item>
              );
            })}
          </Descriptions>
        ) : (
          <div
            style={{
              marginTop: 12,
              padding: "16px 20px",
              borderRadius: "var(--radius-lg)",
              background: "var(--warning-bg)",
              border: "1px solid var(--warning-100)",
              fontSize: 13,
              color: "var(--warning-700)",
            }}
          >
            尚未配置连接参数。点击「配置连接器」填写 {SOURCE_TYPE_LABELS[dataSource.source_type]}{" "}
            所需的连接信息。
          </div>
        )}
      </div>

      {/* Edit Drawer */}
      <Drawer
        title={`编辑连接器配置 — ${SOURCE_TYPE_LABELS[dataSource.source_type]}`}
        size={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        footer={
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={handleSave}>
              保存配置
            </Button>
          </div>
        }
      >
        <div style={{ display: "grid", gap: 16 }}>
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "var(--radius-md)",
              background: "var(--brand-50)",
              border: "1px solid var(--brand-200)",
              fontSize: 12,
              marginBottom: 4,
            }}
          >
            修改连接配置后立即生效，下次同步/接入将使用新配置。
          </div>
          {fields.map((f) => (
            <div key={f.key}>
              <label
                style={{
                  fontSize: 13,
                  fontWeight: 500,
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  marginBottom: 6,
                }}
              >
                {f.label}
                {f.required && <span style={{ color: "var(--danger-600)" }}>*</span>}
                {f.sensitive && (
                  <Tag color="orange" style={{ fontSize: 10, marginLeft: 4 }}>
                    敏感
                  </Tag>
                )}
              </label>
              <Input
                value={formValues[f.key] ?? ""}
                onChange={(e) => setFormValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                type={f.sensitive ? "password" : "text"}
              />
              {f.sensitive && (
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
                  敏感字段仅在编辑时可见，保存后将加密存储
                </div>
              )}
            </div>
          ))}
        </div>
      </Drawer>
    </>
  );
}
