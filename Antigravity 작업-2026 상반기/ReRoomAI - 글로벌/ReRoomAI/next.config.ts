import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Share-page before/after images live in Firebase Storage
    remotePatterns: [
      {
        protocol: "https",
        hostname: "storage.googleapis.com",
      },
    ],
  },
};

export default nextConfig;
