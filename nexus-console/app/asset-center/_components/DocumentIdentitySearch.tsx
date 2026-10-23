"use client";

import { Button, Form, Input } from "antd";
import { Search } from "lucide-react";

import {
  documentIdentityQuery,
  reportDocumentQuery,
  type ReportDocumentFilters,
} from "@/lib/asset-center/document-filters";

export function DocumentIdentitySearch({
  filters,
  onSearch,
  pending,
  withContentTag = false,
}: {
  filters: ReportDocumentFilters;
  onSearch: (filters: ReportDocumentFilters) => void;
  pending: boolean;
  withContentTag?: boolean;
}) {
  const [form] = Form.useForm<ReportDocumentFilters>();
  return (
    <Form
      name="professional-document-search"
      form={form}
      layout="inline"
      initialValues={filters}
      aria-label="专业文档检索"
      className="!ml-auto flex max-w-full flex-wrap justify-end gap-y-2"
      onFinish={(values) =>
        onSearch(withContentTag ? reportDocumentQuery(values) : documentIdentityQuery(values))
      }
    >
      <Form.Item name="major_name" className="!me-2 !mb-0">
        <Input
          aria-label="专业名称"
          placeholder="专业名称"
          allowClear
          maxLength={128}
          className="!w-44"
        />
      </Form.Item>
      <Form.Item name="major_code" className="!me-2 !mb-0">
        <Input
          aria-label="专业代码"
          placeholder="专业代码"
          allowClear
          maxLength={128}
          className="!w-32"
        />
      </Form.Item>
      <Form.Item name="institution_name" className="!me-2 !mb-0">
        <Input
          aria-label="院校名称"
          placeholder="院校名称"
          allowClear
          maxLength={128}
          className="!w-48"
        />
      </Form.Item>
      {withContentTag && (
        <Form.Item name="content_tag" className="!me-2 !mb-0">
          <Input
            aria-label="内容标签"
            placeholder="内容标签关键词"
            allowClear
            maxLength={128}
            className="!w-44"
          />
        </Form.Item>
      )}
      <Form.Item className="!me-2 !mb-0">
        <Button type="primary" htmlType="submit" icon={<Search size={14} />} loading={pending}>
          检索
        </Button>
      </Form.Item>
      <Form.Item className="!me-0 !mb-0">
        <Button
          disabled={pending}
          onClick={() => {
            form.setFieldsValue({
              major_name: "",
              major_code: "",
              institution_name: "",
              content_tag: "",
            });
            onSearch({});
          }}
        >
          重置
        </Button>
      </Form.Item>
    </Form>
  );
}
