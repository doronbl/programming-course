/** @type {import('next').NextConfig} */
const nextConfig = {
  // Fully static export to out/ so the SPA can be hosted on S3 behind
  // CloudFront with no server runtime, no SSR, and no Lambda@Edge.
  output: 'export',
  // The export must not rely on the Next.js image optimization server.
  images: {
    unoptimized: true,
  },
  // Emit directory-style routes (index.html files) which match the
  // CloudFront/S3 default-root-object and SPA fallback behavior.
  trailingSlash: true,
  reactStrictMode: true,
};

module.exports = nextConfig;
