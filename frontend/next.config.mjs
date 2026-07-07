/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Docker 多阶段构建需要 standalone 输出:
  //   - 减小最终镜像体积(不需要把 node_modules 全打进 runtime 镜像)
  //   - server.js 直接可由 `node server.js` 启动
  output: 'standalone',
  // 开发环境代理 /api/* 请求到后端 FastAPI 服务
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001"}/api/:path*`,
      },
    ];
  },
};
export default nextConfig;
