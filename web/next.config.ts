import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 开启 Cache Components 才能用 'use cache' 和 cacheLife。
  // 店铺数据只在重新跑 load_db.py 时才变，没有理由每次请求都回源查一遍。
  cacheComponents: true,
};

export default nextConfig;
