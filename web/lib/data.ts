import { cacheLife } from "next/cache";
import { supabase } from "./supabase";
import type { Restaurant, Claim, Dish } from "./types";

// 一次把全部店铺连同卡片取出来，筛选和搜索在内存里做。
// 现在只有 23 家（计划 30 家），一次查询几十 KB，比让 PostgREST 对嵌套表
// 做过滤简单得多，也避免 N+1。店数上到几百家时再改成数据库端过滤。
export async function getRestaurants(): Promise<Restaurant[]> {
  // 缓存整份店铺数据。提炼是离线预计算的，线上只读——这正是 README 决策 1
  // 说的那个架构，缓存让它名副其实：请求不再每次跨太平洋回源查库。
  // 数据变更来自重新跑 load_db.py，之后重新部署即可刷新。
  "use cache";
  cacheLife("days");

  const { data, error } = await supabase
    .from("restaurants")
    .select(
      `id, name, suburb, address, cuisine, price_min, price_max,
       extractions ( review_count, consistency, scene_tags, scene_basis, vibe, negative_words,
                     claims ( kind, subject, reason, mentions, review_nums, quote ),
                     dishes ( name_raw, search_key, mentions, review_nums, quote ) )`,
    )
    .order("name");
  if (error) throw new Error(`读取店铺失败：${error.message}`);
  return (data ?? []) as unknown as Restaurant[];
}

export async function getRestaurant(id: string): Promise<Restaurant | null> {
  const all = await getRestaurants();
  return all.find((r) => r.id === id) ?? null;
}

export const card = (r: Restaurant) => r.extractions ?? undefined;

export const warnings = (r: Restaurant): Claim[] =>
  (card(r)?.claims ?? [])
    .filter((c) => c.kind === "warning")
    .sort((a, b) => b.mentions - a.mentions);

export const fits = (r: Restaurant): Claim[] =>
  (card(r)?.claims ?? [])
    .filter((c) => c.kind === "fit")
    .sort((a, b) => b.mentions - a.mentions);

export const dishes = (r: Restaurant): Dish[] =>
  (card(r)?.dishes ?? []).slice().sort((a, b) => b.mentions - a.mentions);

export function priceText(r: Restaurant): string | null {
  if (r.price_min == null) return null;
  if (r.price_max == null) return `A$${r.price_min}+`;
  if (r.price_max === r.price_min) return `A$${r.price_min}`;
  return `A$${r.price_min}–${r.price_max}`;
}

// 详情页的「在 Google 地图打开」——照片、地址、营业时间、导航都靠它。
// 用官方的地图链接格式，不需要 API key，也不需要绑卡。
export const mapsUrl = (r: Restaurant) =>
  "https://www.google.com/maps/search/?api=1&query=" +
  encodeURIComponent([r.name, r.suburb, "Sydney"].filter(Boolean).join(" "));

export function matches(r: Restaurant, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  if (r.name.toLowerCase().includes(needle)) return true;
  if ((r.cuisine ?? "").toLowerCase().includes(needle)) return true;
  return dishes(r).some(
    (d) =>
      d.name_raw.toLowerCase().includes(needle) ||
      d.search_key.some((k) => k.includes(needle)),
  );
}
