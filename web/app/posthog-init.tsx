"use client";

import { useEffect } from "react";
import posthog from "posthog-js";

/**
 * 初始化 PostHog。放在根布局里，对所有页面生效。
 *
 * 几个选择：
 * - capture_pageview: "history_change" —— 这个站的筛选和搜索都走 URL query，
 *   用户点场景按钮是客户端路由切换而非整页刷新。设成 true 只会记到首次访问，
 *   后面的翻页全都丢掉。history_change 让 PostHog 自己监听路由变化，
 *   也就不用手写 usePathname/useSearchParams（后者在 Suspense 外会破坏预渲染）。
 * - person_profiles: "always" —— 访客全是匿名的，没有登录。只有给匿名访客
 *   建档，才能算得出「回访率」，而那是计划里第 6 周要看的指标。
 *   PostHog 按事件计费不按人数，免费额度每月 100 万事件，这里用不到 1%。
 * - 没有 key 就直接跳过：本地开发或忘记配环境变量时不报错，不阻断页面。
 */
export function PostHogInit() {
  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (!key) return;
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
      defaults: "2026-08-30",
      capture_pageview: "history_change",
      person_profiles: "always",
    });
  }, []);

  return null;
}
