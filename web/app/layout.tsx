import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Playfair_Display } from "next/font/google";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

const sans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const display = Playfair_Display({
  subsets: ["latin"],
  display: "swap",
  weight: ["500", "600"],
  variable: "--font-display",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500"],
  variable: "--font-mono",
});

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Smriti — diffusion restoration for damaged photographs",
    template: "%s · Smriti",
  },
  description:
    "Repair tears and scratches, reduce noise, colourise, upscale and restore faces in old " +
    "photographs. Diffusion restoration with a fault-tolerant GPU job queue.",
  keywords: [
    "photo restoration",
    "old photo repair",
    "diffusion models",
    "stable diffusion",
    "super resolution",
    "inpainting",
    "colourisation",
    "face restoration",
    "computer vision",
  ],
  authors: [{ name: "Shahriar Ahmed Seam" }],
  openGraph: {
    type: "website",
    url: siteUrl,
    title: "Smriti",
    description:
      "Diffusion restoration for damaged and ageing photographs, with reference-based metrics.",
    siteName: "Smriti",
  },
  twitter: {
    card: "summary_large_image",
    title: "Smriti",
    description: "Diffusion restoration for damaged photographs.",
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#0c0b0a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${mono.variable}`}>
      <body className="min-h-dvh">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50
            focus:rounded-lg focus:bg-turmeric focus:px-4 focus:py-2 focus:text-ink"
        >
          Skip to content
        </a>
        <div className="flex min-h-dvh flex-col">
          <SiteHeader />
          <main id="main" className="flex-1">
            {children}
          </main>
          <SiteFooter />
        </div>
      </body>
    </html>
  );
}
