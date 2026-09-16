export type Claim = {
  kind: "fit" | "warning";
  subject: string;
  reason: string | null;
  mentions: number;
  review_nums: number[];
  quote: string | null;
};

export type Dish = {
  name_raw: string;
  search_key: string[];
  mentions: number;
  review_nums: number[];
  quote: string | null;
};

export type Extraction = {
  review_count: number;
  consistency: string | null;
  scene_tags: string[];
  scene_basis: string | null;
  vibe: string[];
  negative_words: string[];
  claims: Claim[];
  dishes: Dish[];
};

export type Restaurant = {
  id: string;
  name: string;
  suburb: string | null;
  address: string | null;
  cuisine: string | null;
  price_min: number | null;
  price_max: number | null;
  // PostgREST 返回的是对象不是数组：restaurants 与 extractions 之间是一对一
  // （extractions.restaurant_id 上有唯一约束），它会据此判定关系基数。
  extractions: Extraction | null;
};

// 官方地址里 Sydney 是 CBD 核心那个 suburb，和 Haymarket 并列而非包含。
// 但用户读到「Sydney」会理解成整座城市，与旁边的 Haymarket、Redfern 摆在一起
// 像是层级错误。这里只改显示名，数据库里仍存官方 suburb。
export const SUBURB_LABELS: Record<string, string> = {
  Sydney: "Sydney CBD",
};

export const suburbLabel = (s: string) => SUBURB_LABELS[s] ?? s;

export const SCENES: Record<string, string> = {
  date: "约会",
  friends: "朋友聚餐",
  family: "带父母",
};
