import type { Metadata } from "next";

import { SessionProvider } from "@/lib/session";
import { strings } from "@/lib/strings";

import "./globals.css";

export const metadata: Metadata = {
  title: `${strings.brand.name} — ${strings.brand.tagline}`,
  description:
    "Multi-tenant fleet management: live tracking, dispatch, maintenance and fleet analytics.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
