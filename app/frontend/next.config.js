/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://backend:8080/:path*',
      },
      {
        source: '/static/:path*',
        destination: 'http://backend:8080/static/:path*',
      }
    ];
  }
};

module.exports = nextConfig;