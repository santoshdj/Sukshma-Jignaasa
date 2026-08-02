import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sukshma-Jignaasa",
  description: "AI companion for rare disease pattern detection",
  manifest: "/manifest.json",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-slate-50 text-slate-900 antialiased min-h-screen">
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
