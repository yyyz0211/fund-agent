/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Docker 多阶段构建需要 standalone 输出:
  //   - 减小最终镜像体积(不需要把 node_modules 全打进 runtime 镜像)
  //   - server.js 直接可由 `node server.js` 启动
  output: 'standalone',
};
export default nextConfig;
