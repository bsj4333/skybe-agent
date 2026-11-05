/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // Dev only: `next dev` proxies API calls. The exported site is served by FastAPI itself.
  ...(process.env.NODE_ENV === "development"
    ? { async rewrites() { return [{ source: "/api/:path*", destination: `${process.env.SKIVE_API ?? "http://127.0.0.1:8010"}/api/:path*` }]; } }
    : {}),
};

export default nextConfig;
