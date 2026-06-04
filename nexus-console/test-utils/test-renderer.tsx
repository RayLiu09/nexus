import type { ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider, App as AntdApp } from "antd";
import zhCN from "antd/locale/zh_CN";

function TestWrapper({ children }: { children: ReactNode }) {
  return (
    <AntdRegistry>
      <ConfigProvider locale={zhCN}>
        <AntdApp>{children}</AntdApp>
      </ConfigProvider>
    </AntdRegistry>
  );
}

type CustomRenderOptions = Omit<RenderOptions, "wrapper">;

export function renderWithProviders(ui: ReactNode, options?: CustomRenderOptions) {
  return {
    user: userEvent.setup(),
    ...render(ui, { wrapper: TestWrapper, ...options }),
  };
}

export { screen, within } from "@testing-library/react";
export { userEvent };
