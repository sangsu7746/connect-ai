import type { Metadata } from "next";
import { Noto_Serif } from "next/font/google";
import "./globals.css";

const notoSerif = Noto_Serif({
  weight: ["400", "600", "700", "900"],
  subsets: ["latin"],
  variable: "--font-noto-serif",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://reroom-ai.vercel.app"),
  title: "ReRoom AI — AI Interior Design & Virtual Staging in Seconds",
  description:
    "Upload a room photo, pick a style, and AI redesigns the space in ~10 seconds. Virtually stage empty listings from $0.10 per photo — walls and windows stay exactly the same.",
  openGraph: {
    title: "ReRoom AI — AI Interior Design & Virtual Staging in Seconds",
    description:
      "Upload a room photo, pick a style, and AI redesigns the space in ~10 seconds. Virtual staging for realtors from $0.10 per photo.",
    url: "https://reroom-ai.vercel.app",
    siteName: "ReRoom AI",
    images: [
      {
        url: "/living_room_after.png",
        width: 1200,
        height: 1200,
        alt: "Living room redesigned by ReRoom AI in Japandi style",
      },
    ],
    locale: "en_US",
    type: "website",
  },
  icons: {
    icon: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`h-full antialiased ${notoSerif.variable}`}>
      <body className="min-h-full flex flex-col bg-paper text-ink font-sans">
        {children}
      </body>
    </html>
  );
}
