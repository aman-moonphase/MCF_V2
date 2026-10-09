import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Header } from "@/components/layout/header";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider } from "@/contexts/AuthContext";
import { Toaster } from "@/components/ui/sonner";

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
  title: "MCF Content Studio",
  description: "AI-powered multimodal content factory",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} min-h-full flex flex-col bg-background text-foreground relative selection:bg-primary/30 antialiased`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <AuthProvider>
            <div className="fixed inset-0 z-[-2] bg-grid bg-[size:40px_40px] opacity-100 pointer-events-none" />
            <div className="fixed inset-0 z-[-1] pointer-events-none bg-[radial-gradient(ellipse_100%_100%_at_50%_-20%,rgba(99,102,241,0.15),var(--background)_60%)]" />
            <Header />
            <main className="flex-1 flex flex-col pt-24 sm:pt-28">{children}</main>
          </AuthProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
