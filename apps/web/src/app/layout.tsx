import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { BusinessRouteShell } from "@/components/layout/business-route-shell";
import { AppProviders } from "@/components/providers/app-providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "红人智采 · Influencer Intel",
  description: "海外红人数据采集与管理系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <AppProviders>
          <BusinessRouteShell>{children}</BusinessRouteShell>
        </AppProviders>
      </body>
    </html>
  );
}
