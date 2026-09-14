import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "STEPS アンケート読取",
  description: "来場者アンケートの公演回・年齢を読み取ります。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
