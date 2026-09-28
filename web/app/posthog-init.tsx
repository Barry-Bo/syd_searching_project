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
    // 环境变量优先，取不到就用写死的值。
    //
    // 直接把 key 写进代码是有意的：PostHog 的 Project API Key 按设计就是公开的，
    // 它必然会被打进浏览器 JS，任何访客 F12 都能看到，写不写在源码里不改变这一点。
    // 之所以不只依赖环境变量：首次部署后客户端 bundle 里查不到这个值，
    // 说明构建时没拿到它，而 PostHog 初始化在浏览器端、必须在构建时就把值内联进去。
    // 与其继续排查 Vercel 的变量配置，不如去掉这个环节——埋点每晚上线一天，
    // 就少一天永远补不回来的访问数据。
    // （真正不能进代码的是 phx_ 开头的 Personal API Key 和 sb_secret_ 开头的那把。）
    const envKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    // 用真值判断而不是 ??：Vercel 上这个变量存在但值是空字符串，
    // 而 ?? 只在 null/undefined 时兜底，空字符串会原样通过，
    // 再被下面的 if (!key) 拦掉——这正是前两次部署埋点没启动的原因。
    const key = envKey && envKey.startsWith("phc_") ? envKey : "phc_qFQy4TTHKWRTkM7Vf3EFNUSaDzo4mBzew6NvsjKfvefn";
    const envHost = process.env.NEXT_PUBLIC_POSTHOG_HOST;
    // 同样的坑：这个变量在 Vercel 上也是空字符串。空的 api_host 会让
    // PostHog 按相对路径请求，结果打到本站域名并全部 404。
    const host =
      envHost && envHost.startsWith("http") ? envHost : "https://us.i.posthog.com";
    if (!key) return;
    posthog.init(key, {
      api_host: host,
      defaults: "2026-08-30",
      capture_pageview: "history_change",
      person_profiles: "always",
    });
  }, []);

  return null;
}
