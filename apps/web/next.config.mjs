/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const api = process.env.AEROPKMECH_API_ORIGIN || 'http://127.0.0.1:8000';
    return [
      { source: '/api/:path*', destination: `${api}/api/:path*` },
      { source: '/vendor/:path*', destination: `${api}/vendor/:path*` },
      { source: '/app.js', destination: `${api}/app.js` },
      { source: '/style.css', destination: `${api}/style.css` },
    ];
  },
};
export default nextConfig;
