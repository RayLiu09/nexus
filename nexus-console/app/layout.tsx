import type { Metadata } from "next";
import Link from "next/link";
import { navItems } from "@/lib/navigation";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEXUS Console",
  description: "NEXUS enterprise data and knowledge asset console"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <Link className="brand" href="/workbench">
              <strong>NEXUS</strong>
              <span>数据与知识资产平台</span>
            </Link>
            <nav className="nav-list" aria-label="P0 pages">
              {navItems.map((item) => (
                <Link className="nav-item" href={item.href} key={item.href}>
                  <span>{item.label}</span>
                  <span className="nav-id">{item.prototypeId}</span>
                </Link>
              ))}
            </nav>
          </aside>
          <main className="main-area">
            <header className="topbar">
              <span className="topbar-title">P0 控制台</span>
              <span className="topbar-meta">本地身份 / LiteLLM 引用 / RAGFlow 集成边界</span>
            </header>
            <div className="content">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
