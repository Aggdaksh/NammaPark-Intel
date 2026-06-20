import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NammaPark Intel",
  description: "Parking enforcement intelligence console for Bengaluru traffic operations.",
  icons: {
    icon: "/assets/nammapark-favicon.svg"
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
