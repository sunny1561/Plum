import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Plum Claims Processor",
  description: "AI-powered health insurance claims processing",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <header className="border-b border-gray-800 bg-gray-900">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-plum-600 flex items-center justify-center text-white font-bold text-sm">
              P
            </div>
            <div>
              <span className="font-semibold text-white">Plum</span>
              <span className="text-gray-400 ml-2 text-sm">Claims Processing System</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">
                v1.0.0
              </span>
              <span className="text-xs text-green-400 bg-green-900/30 px-2 py-1 rounded border border-green-800">
                Live
              </span>
            </div>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
