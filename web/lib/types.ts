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

export const SCENES: Record<string, string> = {
  date: "约会",
  friends: "朋友聚餐",
  family: "带父母",
};
