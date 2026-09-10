-- SydBite 数据库结构
-- 在 Supabase 后台 SQL Editor 里整份粘贴执行。可重复执行（用了 if not exists）。
--
-- 五个设计决策及其来源：
--   1. 菜品与结论拆成独立表——要支持「搜麻婆豆腐出来哪几家店」这类跨店查询
--   2. 只存当前生效的一版，历史版本靠 git 里的 pipeline/out/；
--      另设 extraction_runs 记录每次跑批的成本与规模
--   3. 只存「原句」片段，不存评论全文——Google 条款对缓存评论内容有限制，
--      开发用的全文留在本地 pipeline/samples/
--   4. feedback 分两层：第一层问观感（人人能答），第二层问事实（只有去过的人能答）
--   5. 菜名存两份：name_raw 给用户对照菜单点菜，search_key 给跨语言检索

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- 店铺主体
create table if not exists restaurants (
  id                 uuid primary key default gen_random_uuid(),
  -- Places API 尚未接入，现有 23 家店没有 place_id，接通后回填。
  -- 它是 Google 条款里唯一允许长期缓存的字段。
  place_id           text unique,
  name               text not null,
  address            text,     -- 受访者 03「列出地址、价位、营业时间」
  suburb             text,
  lat                double precision,
  lng                double precision,
  rating             numeric(2,1),
  user_ratings_total integer,
  price_level        smallint check (price_level between 0 and 4),
  -- 人均价位（澳元/人）。Places API 因支付受阻放弃后，改为手动从 Google 地图
  -- 店铺页抄录。price_level 是 Google 的 0-4 级枚举，装不下「A$20–40」这种写法。
  -- 「A$100+」这类开口区间：price_min=100，price_max 留空。
  price_min          smallint,
  price_max          smallint,
  -- 人均价位，单位澳元/人。Places API 放弃后改为手动从 Google 地图店铺页抄录，
  -- 那里显示的是「A$20–40」这种区间，price_level 的 0-4 级装不下。
  -- 「A$100+」这类开放区间：price_min=100，price_max 留空。
  price_min          smallint,
  price_max          smallint,
  cuisine            text,
  -- 以下同样来自 Places API，接通前全为 null。
  -- 用户反馈明确要求：朋友 F「外卖支持与否，儿童宠物友好与否，人均价格」、
  -- 受访者 03「地址、价位、营业时间」。现在留好列，接通后回填即可，不必改表。
  takeout            boolean,
  delivery           boolean,
  good_for_children  boolean,
  allows_dogs        boolean,
  opening_hours      jsonb,
  photo_refs         text[],   -- 朋友 D「有图片就更好了」
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists idx_restaurants_suburb on restaurants (suburb);

-- 补列：create table if not exists 对已经存在的表不生效，所以加过的列要单独 alter，
-- 否则先建库的人永远拿不到后加的字段。这两条都是幂等的，重复执行无害。
alter table restaurants add column if not exists address text;
alter table restaurants add column if not exists price_min smallint;
alter table restaurants add column if not exists price_max smallint;
-- 上限不得小于下限、不得为负。手抄时把「40–20」写反，写入即被拒，
-- 而不是悄悄存下一个错的价格。约束先删后加，保证可重复执行。
alter table restaurants drop constraint if exists restaurants_price_range;
alter table restaurants add constraint restaurants_price_range check (
  (price_min is null or price_min >= 0)
  and (price_max is null or price_min is null or price_max >= price_min)
);
alter table restaurants add column if not exists price_min smallint;
alter table restaurants add column if not exists price_max smallint;
-- Postgres 的 add constraint 不支持 if not exists，先删后加保证可重复执行
alter table restaurants drop constraint if exists restaurants_price_range;
alter table restaurants add constraint restaurants_price_range check (
  (price_min is null or price_min >= 0)
  and (price_max is null or price_min is null or price_max >= price_min)
);

-- ---------------------------------------------------------- 每次跑批的记录
-- 计划第 2 周要求「记录每次运行的 API 调用数和花费」。
create table if not exists extraction_runs (
  id               uuid primary key default gen_random_uuid(),
  prompt_version   text not null,
  model            text not null,
  started_at       timestamptz not null default now(),
  finished_at      timestamptz,
  stores_total     integer,
  stores_ok        integer,
  stores_failed    integer,
  tokens_in        bigint,
  tokens_out       bigint,
  tokens_reasoning bigint,   -- 推理模型的思考 token，实测占输出的 89-95%
  cost_cny         numeric(10,4),
  notes            text
);

-- ------------------------------------------------------------ 卡片主体
-- 一店一行（restaurant_id 唯一）。数组字段用 text[] 而非独立表：
-- 它们是固定枚举的短标签、没有子字段，GIN 索引足以支撑筛选。
create table if not exists extractions (
  id             uuid primary key default gen_random_uuid(),
  restaurant_id  uuid not null unique references restaurants(id) on delete cascade,
  run_id         uuid references extraction_runs(id) on delete set null,
  review_count   smallint not null check (review_count > 0),
  consistency    text check (consistency in ('高','中','低')),
  scene_tags     text[] not null default '{}',  -- date/friends/family/solo
  scene_basis    text,                          -- 场景依据：指认线索，防止凭菜系猜测
  vibe           text[] not null default '{}',
  negative_words text[] not null default '{}',  -- 高频负面词
  created_at     timestamptz not null default now()
);
create index if not exists idx_extractions_scene on extractions using gin (scene_tags);
create index if not exists idx_extractions_vibe  on extractions using gin (vibe);
create index if not exists idx_extractions_neg   on extractions using gin (negative_words);

-- --------------------------------------------------- 带依据的结论（适合/慎选）
-- 「适合」与「慎选」结构完全相同，用 kind 区分，不必拆成两张表。
create table if not exists claims (
  id            uuid primary key default gen_random_uuid(),
  extraction_id uuid not null references extractions(id) on delete cascade,
  kind          text not null check (kind in ('fit','warning')),
  subject       text not null,          -- 人群或场合 / 提醒
  reason        text,                   -- 依据 / 原因
  mentions      smallint not null check (mentions > 0),
  review_nums   smallint[] not null,    -- 依据来自第几条评论
  quote         text,                   -- 逐字原句，保留原语言
  -- verify.py 里最有效的那条校验，搬进存储层：
  -- 提及次数必须等于评论编号的个数，不自洽的数据根本写不进来。
  constraint claims_mentions_match check (mentions = cardinality(review_nums))
);
create index if not exists idx_claims_extraction on claims (extraction_id);
create index if not exists idx_claims_kind on claims (kind, mentions desc);

-- ------------------------------------------------------------------ 必点菜品
create table if not exists dishes (
  id            uuid primary key default gen_random_uuid(),
  extraction_id uuid not null references extractions(id) on delete cascade,
  -- 展示用：保留评论里的原始写法，用户要拿着它对照菜单点菜
  name_raw      text not null,
  -- 检索用：由独立的规范化步骤生成，含中英两种写法
  -- 例：['fried chicken', '炸鸡']。prompt 不负责翻译，职责分开。
  search_key    text[] not null default '{}',
  mentions      smallint not null check (mentions > 0),
  review_nums   smallint[] not null,
  quote         text,
  constraint dishes_mentions_match check (mentions = cardinality(review_nums))
);
create index if not exists idx_dishes_extraction on dishes (extraction_id);
create index if not exists idx_dishes_key on dishes using gin (search_key);

-- ------------------------------------------------------------------ 搜索日志
create table if not exists search_logs (
  id           uuid primary key default gen_random_uuid(),
  session_id   text not null,
  query        text not null,          -- 用户输入的原话，不做任何清洗
  parsed       jsonb,                  -- LLM 解析出的结构化查询
  result_ids   uuid[],                 -- 返回了哪几家，按顺序
  clicked_id   uuid references restaurants(id) on delete set null,
  clicked_rank smallint,               -- 点的是第几个，用来判断推荐准不准
  created_at   timestamptz not null default now()
);
create index if not exists idx_search_logs_time on search_logs (created_at desc);

-- -------------------------------------------------------------------- 反馈
-- 两层：useful 人人能答，用来算比例；visited/accurate 只有去过的人能答，
-- 数据量小但可以直接用来修正卡片。第二层来自用户建议
-- 「点评完了其他人去了，觉得符合你的评价会给你点个赞」。
create table if not exists feedback (
  id            uuid primary key default gen_random_uuid(),
  restaurant_id uuid not null references restaurants(id) on delete cascade,
  session_id    text not null,
  useful        text not null check (useful in ('yes','partly','no')),
  visited       boolean,
  accurate      text check (accurate in ('accurate','partly','wrong')),
  wrong_field   text,   -- 哪个字段不准：warning / dish / fit / scene / vibe
  comment       text,
  created_at    timestamptz not null default now(),
  -- 没去过就不该有准确性判断
  constraint feedback_accurate_needs_visit
    check (accurate is null or visited is true)
);
create index if not exists idx_feedback_restaurant on feedback (restaurant_id);

-- =================================================================== 权限
-- 建项目时勾了 automatic RLS，新表默认拒绝一切访问，必须显式开口子。
-- 权限模型：展示数据只读不写，行为数据只写不读。
alter table restaurants     enable row level security;
alter table extractions     enable row level security;
alter table claims          enable row level security;
alter table dishes          enable row level security;
alter table search_logs     enable row level security;
alter table feedback        enable row level security;
alter table extraction_runs enable row level security;

-- 展示数据：匿名用户只能读。写入由离线管线用 service_role 完成（绕过 RLS）。
drop policy if exists p_read_restaurants on restaurants;
create policy p_read_restaurants on restaurants for select to anon using (true);
drop policy if exists p_read_extractions on extractions;
create policy p_read_extractions on extractions for select to anon using (true);
drop policy if exists p_read_claims on claims;
create policy p_read_claims on claims for select to anon using (true);
drop policy if exists p_read_dishes on dishes;
create policy p_read_dishes on dishes for select to anon using (true);

-- 行为数据：匿名用户只能写，不能读。
-- 不给 select 是为了防止别人扒走全部搜索日志——那是这个产品最有价值的数据。
drop policy if exists p_write_search_logs on search_logs;
create policy p_write_search_logs on search_logs for insert to anon with check (true);
drop policy if exists p_write_feedback on feedback;
create policy p_write_feedback on feedback for insert to anon with check (true);

-- extraction_runs 不对匿名开放任何权限：成本数据只有你自己该看到。

-- =========================================================== 表级授权
-- GRANT 和 RLS 是两层，缺一不可：GRANT 决定「能不能碰这张表」，
-- RLS 决定「能碰哪些行」。上面那套 policy 只写了第二层，
-- 而新建的 Supabase 项目不再自动给这些角色授权，所以第一层必须显式写出来。
-- （症状：service_role 写入时报 42501 permission denied，而不是被 RLS 挡住。）

grant usage on schema public to anon, service_role;

-- 离线管线：全部读写。service_role 同时绕过 RLS，所以它不受上面 policy 限制。
grant select, insert, update, delete on
  restaurants, extraction_runs, extractions, claims, dishes, search_logs, feedback
  to service_role;

-- 前端匿名用户：展示数据只读，行为数据只写不读。
-- 授权范围必须和上面的 policy 一致，否则等于开了后门。
grant select on restaurants, extractions, claims, dishes to anon;
grant insert on search_logs, feedback to anon;

-- extraction_runs 不给 anon 任何授权：成本数据只有你自己该看到。
