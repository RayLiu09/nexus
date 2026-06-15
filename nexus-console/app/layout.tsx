import type { Metadata } from "next";
import { Inter_Tight, JetBrains_Mono } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { Providers } from "./providers";
import "./globals.css";

// 全局 sans —— 比 Inter 略紧凑，工程感更强；提供 400/500/600/700 四档
const interTight = Inter_Tight({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans-loaded",
  display: "swap",
});

// Mono —— 仅供 code/ID 等场景；数值列用 .text-num（sans + tabular-nums）
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-loaded",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NEXUS Console",
  description: "NEXUS enterprise data and knowledge asset console",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${interTight.variable} ${jetbrainsMono.variable}`}>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
