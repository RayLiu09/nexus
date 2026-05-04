import Link from "next/link";
import { StatusLabel } from "@/components/StatusLabel";
import { week2Demo } from "@/lib/week2-demo";

export default function AssetsPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-06</p>
          <h1>资产目录</h1>
          <p>展示由接入链路生成的资产、派生当前版本和标准化引用。</p>
        </div>
        <button className="primary-button">上传资产</button>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>标题</span>
          <span>资产ID</span>
          <span>类型</span>
          <span>当前版本</span>
          <span>标准化引用</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <div className="table-row">
          <span>{week2Demo.title}</span>
          <span>{week2Demo.assetId}</span>
          <span>document</span>
          <span>{week2Demo.versionId}</span>
          <span>{week2Demo.normalizedRefId}</span>
          <StatusLabel value="available" />
          <Link className="text-link" href={`/assets/${week2Demo.assetId}`}>
            查看详情
          </Link>
        </div>
      </div>
    </section>
  );
}
