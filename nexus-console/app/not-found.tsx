import Link from "next/link";
import { Button, Result } from "antd";

export default function NotFoundPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <Result
        status="404"
        title="页面未找到"
        subTitle="当前访问的页面不存在或已被移除。"
        extra={
          <Link href="/workbench">
            <Button type="primary">返回工作台</Button>
          </Link>
        }
      />
    </div>
  );
}
