"use client";

import { Button, Form, Input } from "antd";
import { Search } from "lucide-react";

import { documentTagQuery, type DocumentTagFilters } from "@/lib/asset-center/document-filters";

export function DocumentTagSearch({
  filters,
  onSearch,
  pending,
}: {
  filters: DocumentTagFilters;
  onSearch: (filters: DocumentTagFilters) => void;
  pending: boolean;
}) {
  const [form] = Form.useForm<DocumentTagFilters>();
  return (
    <Form
      form={form}
      layout="inline"
      initialValues={filters}
      aria-label="自定义检索"
      className="!ml-auto flex max-w-full flex-wrap justify-end gap-y-2"
      onFinish={(values) => onSearch(documentTagQuery(values))}
    >
      <Form.Item name="region" className="!me-2 !mb-0">
        <Input
          aria-label="区域"
          placeholder="区域，如重庆市"
          allowClear
          maxLength={128}
          className="!w-40"
        />
      </Form.Item>
      <Form.Item name="industry" className="!me-2 !mb-0">
        <Input
          aria-label="行业"
          placeholder="行业，如电子商务"
          allowClear
          maxLength={128}
          className="!w-44"
        />
      </Form.Item>
      <Form.Item name="content_tag" className="!me-2 !mb-0">
        <Input
          aria-label="内容标签"
          placeholder="内容标签关键词"
          allowClear
          maxLength={128}
          className="!w-44"
        />
      </Form.Item>
      <Form.Item className="!me-2 !mb-0">
        <Button type="primary" htmlType="submit" icon={<Search size={14} />} loading={pending}>
          检索
        </Button>
      </Form.Item>
      <Form.Item className="!me-0 !mb-0">
        <Button
          disabled={pending}
          onClick={() => {
            form.setFieldsValue({ region: "", industry: "", content_tag: "" });
            onSearch({});
          }}
        >
          重置
        </Button>
      </Form.Item>
    </Form>
  );
}
