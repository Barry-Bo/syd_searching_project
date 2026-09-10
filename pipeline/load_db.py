#!/usr/bin/env python3
"""把 out/ 里的卡片连同 samples/ 里的评论条数写进 Supabase。

用法：
    python3 pipeline/load_db.py --dry-run          # 只打印要写什么，不碰数据库
    python3 pipeline/load_db.py                    # 真写，默认 v5
    python3 pipeline/load_db.py --prompt v5 --model qwen3.7-flash

只用标准库，走 PostgREST（Supabase 的 REST 接口），用 service_role key 绕过 RLS。

四个实现决策：

1. **重复执行安全。** 每家店先按 name 查，查到就复用 id，查不到才插入；
   卡片用 on_conflict=restaurant_id 覆盖；claims/dishes 先删后插。
   所以这个脚本可以反复跑，不会产生重复数据。

2. **为什么按 name 查而不是 upsert。** restaurants 的唯一键是 place_id，
   而 Places API 还没接通，23 家店的 place_id 全是 null——Postgres 里
   null 彼此不相等，upsert 会每跑一次插一批新行。name 上没有加唯一约束是
   故意的：杨国福这类连锁店在不同区会重名，将来接通 place_id 后才是真正的身份。
   现阶段 23 家店没有重名，按 name 查是安全的。

3. **search_key 现在只做规范化，不做翻译。** schema 里这个字段的设计是中英两份
   （例 ['fried chicken', '炸鸡']），但翻译需要再过一次 LLM，属于独立步骤，
   不塞进入库脚本。现在只写小写去标点的原名，中文菜名天然就是中文键。
   跨语言检索要等那一步补上——这是已知缺口，不是遗漏。

4. **extraction_runs 这次是回填。** run_all.py 当时只把 token 和花费打印到
   终端，没有落盘，所以本次运行的数字取自 docs/data-quality.md 的质检记录，
   并在 notes 里注明是回填。下次跑批前应让 run_all.py 直接写这张表。
"""
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import ROOT, load_env  # noqa: E402  复用同一份 .env.local 读取逻辑

# 本次入库对应的跑批元数据。来源：docs/data-quality.md（2026-09-02，23 家店）。
# run_all.py 没有分别记录输入/输出 token，只有总数，所以那两列留空，总数写进 notes。
RUN_META = {
    "stores_total": 23,
    "stores_ok": 23,
    "stores_failed": 0,
    "cost_cny": 0.116,
    "notes": "回填自 docs/data-quality.md：183,349 token（当时未分别记录 in/out），"
             "verify.py 23/23 通过。手动评论通道，非 Places API。",
}


# ------------------------------------------------------------------ HTTP
def api(env, method, path, body=None, prefer=None):
    """调一次 PostgREST。失败直接退出并打印服务端原文——这类错误全都要人看。"""
    url = env["NEXT_PUBLIC_SUPABASE_URL"].rstrip("/") + "/rest/v1" + path
    key = env["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        sys.exit(f"\n✗ {method} {path} → HTTP {e.code}\n  "
                 + e.read().decode("utf-8", "replace")[:600])
    except urllib.error.URLError as e:
        sys.exit(f"\n✗ {method} {path} → 连不上：{e.reason}")


def eq(value):
    """把一个值拼成 PostgREST 的 eq. 过滤条件。

    店名里有 | ( ) ' ! 和韩文，必须先用双引号包起来再整体百分号编码，
    否则 PostgREST 会把 , 和 ( 当成语法。
    """
    return "eq." + urllib.parse.quote(f'"{value}"', safe="")


# ------------------------------------------------------------- 数据转换
def norm_key(name):
    """菜名 → 检索键：小写、去标点、压空格。不翻译（见文件头决策 3）。"""
    s = re.sub(r"[^\w一-鿿]+", " ", name.lower())
    return re.sub(r"\s+", " ", s).strip()


def claims_of(card):
    """「适合」和「慎选」结构相同，用 kind 区分，合并成一张表的行。"""
    rows = []
    for item in card.get("适合") or []:
        rows.append({
            "kind": "fit",
            "subject": item["人群或场合"],
            "reason": item.get("依据"),
            "mentions": item["提及"],
            "review_nums": item["评论编号"],
            "quote": item.get("原句"),
        })
    for item in card.get("慎选") or []:
        rows.append({
            "kind": "warning",
            "subject": item["提醒"],
            "reason": item.get("原因"),
            "mentions": item["提及"],
            "review_nums": item["评论编号"],
            "quote": item.get("原句"),
        })
    return rows


def dishes_of(card):
    return [{
        "name_raw": d["菜名"],
        "search_key": [k for k in [norm_key(d["菜名"])] if k],
        "mentions": d["提及"],
        "review_nums": d["评论编号"],
        "quote": d.get("原句"),
    } for d in card.get("必点") or []]


def check_local(name, card, review_count):
    """入库前先在本地过一遍数据库那几条约束，把错误挡在网络请求之前。

    数据库有 CHECK (mentions = cardinality(review_nums))，不自洽的数据本来就
    写不进去，但让它在这里报错能一次看到全部问题，而不是一家一家试。
    """
    errs = []
    if review_count <= 0:
        errs.append("评论条数为 0")
    if card.get("一致性") not in ("高", "中", "低", None):
        errs.append(f"一致性取值非法：{card.get('一致性')!r}")
    for tag in card.get("场景标签") or []:
        if tag not in ("date", "friends", "family", "solo"):
            errs.append(f"场景标签非法：{tag!r}")
    for row in claims_of(card) + dishes_of(card):
        if row["mentions"] != len(row["review_nums"]):
            errs.append(f"提及次数与评论编号个数不符：{row.get('subject') or row.get('name_raw')!r}"
                        f"（{row['mentions']} vs {len(row['review_nums'])}）")
        for n in row["review_nums"]:
            if not 1 <= n <= review_count:
                errs.append(f"评论编号越界：{row.get('subject') or row.get('name_raw')!r} → {n}")
    return errs


# ------------------------------------------------------------------ 主流程
def collect(version, model):
    """把 samples/*.json 和 out/*__版本__模型.json 配成对。缺一不可。"""
    pairs, missing = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, "pipeline", "samples", "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(ROOT, "pipeline", "out", f"{stem}__{version}__{model}.json")
        if not os.path.exists(out):
            missing.append(stem)
            continue
        sample = json.load(open(path, encoding="utf-8"))
        pairs.append((sample["name"], len(sample["reviews"]),
                      json.load(open(out, encoding="utf-8")),
                      sample.get("places")))   # fetch.py 拉过才有，手动通道的店为 None
    return pairs, missing


def restaurant_cols(name, places):
    """samples 里的 places 块 → restaurants 表的列。

    places 块的键名当初就是照着列名起的，所以这里只做白名单过滤，不做改名——
    多出来的 display_name / address 之外的键（如 fetched_at）留在文件里备查，不入库。
    """
    cols = {"name": name}
    if not places:
        return cols
    allowed = ("place_id", "address", "suburb", "lat", "lng", "rating",
               "user_ratings_total", "price_level", "cuisine", "takeout", "delivery",
               "good_for_children", "allows_dogs", "opening_hours", "photo_refs")
    cols.update({k: v for k, v in places.items() if k in allowed and v is not None})
    return cols


def get_or_create_restaurant(env, name, places=None):
    """先按 place_id 认人，没有再按 name。

    place_id 是 Google 条款里唯一允许长期缓存的字段，也是这家店真正的身份：
    店名会改、会有连锁重名，place_id 不会。所以一旦 fetch.py 补上了它，
    就以它为准——这样将来改了店名也不会重复插入。
    """
    cols = restaurant_cols(name, places)
    pid = cols.get("place_id")

    found = None
    if pid:
        found = api(env, "GET", f"/restaurants?place_id={eq(pid)}&select=id")
    if not found:
        found = api(env, "GET", f"/restaurants?name={eq(name)}&select=id")

    if found:
        rid = found[0]["id"]
        if len(cols) > 1:   # 除 name 外还有东西可写才发这次请求
            api(env, "PATCH", f"/restaurants?id=eq.{rid}",
                dict(cols, updated_at="now()"), prefer="return=minimal")
        return rid, False

    row = api(env, "POST", "/restaurants", [cols], prefer="return=representation")
    return row[0]["id"], True


def main():
    args = sys.argv[1:]
    version = args[args.index("--prompt") + 1] if "--prompt" in args else "v5"
    model = args[args.index("--model") + 1] if "--model" in args else "qwen3.7-flash"
    dry = "--dry-run" in args

    env = load_env()
    for key in ("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if not env.get(key):
            sys.exit(f".env.local 里 {key} 是空的")

    pairs, missing = collect(version, model)
    if missing:
        print(f"⚠ 这些店没有 {version}/{model} 的输出，跳过：{'、'.join(missing)}\n")
    if not pairs:
        sys.exit(f"out/ 下没有任何 {version}__{model} 的卡片")

    # 先在本地把全部校验跑完，有错就不写库——避免写一半留下不完整数据
    bad = [(n, e) for n, rc, c, _ in pairs for e in [check_local(n, c, rc)] if e]
    if bad:
        print("✗ 入库前校验未通过：\n")
        for n, errs in bad:
            print(f"  {n}")
            for e in errs:
                print(f"    - {e}")
        sys.exit(1)

    print(f"prompt {version} · {model} · {len(pairs)} 家店"
          + ("　（dry-run，不写库）" if dry else "") + "\n")

    n_places = sum(1 for *_, p in pairs if p)
    print(f"其中 {n_places}/{len(pairs)} 家有 Places API 字段"
          + ("　（其余走的是手动通道，接通后跑 fetch.py --refresh 补齐）"
             if n_places < len(pairs) else "") + "\n")

    if dry:
        for name, rc, card, places in pairs:
            cl, di = claims_of(card), dishes_of(card)
            fit = sum(1 for c in cl if c["kind"] == "fit")
            extra = ""
            if places:
                extra = f"　价位{places.get('price_level')}　图{len(places.get('photo_refs') or [])}"
            print(f"  {name[:34]:<36}评论{rc}　适合{fit}　慎选{len(cl)-fit}　必点{len(di)}"
                  f"　场景{','.join(card.get('场景标签') or []) or '—'}{extra}")
        print(f"\n本地校验全部通过。去掉 --dry-run 即可真正写入。")
        return

    run = api(env, "POST", "/extraction_runs",
              [dict(RUN_META, prompt_version=version, model=model)],
              prefer="return=representation")[0]
    print(f"跑批记录 id：{run['id']}\n")

    n_new = n_claims = n_dishes = 0
    for name, review_count, card, places in pairs:
        rid, created = get_or_create_restaurant(env, name, places)
        n_new += created

        ext = api(env, "POST", "/extractions?on_conflict=restaurant_id", [{
            "restaurant_id": rid,
            "run_id": run["id"],
            "review_count": review_count,
            "consistency": card.get("一致性"),
            "scene_tags": card.get("场景标签") or [],
            "scene_basis": card.get("场景依据"),
            "vibe": card.get("vibe") or [],
            "negative_words": card.get("高频负面词") or [],
        }], prefer="resolution=merge-duplicates,return=representation")[0]

        # 重跑时先清掉旧的结论和菜品，避免累积
        api(env, "DELETE", f"/claims?extraction_id=eq.{ext['id']}", prefer="return=minimal")
        api(env, "DELETE", f"/dishes?extraction_id=eq.{ext['id']}", prefer="return=minimal")

        cl = [dict(r, extraction_id=ext["id"]) for r in claims_of(card)]
        di = [dict(r, extraction_id=ext["id"]) for r in dishes_of(card)]
        if cl:
            api(env, "POST", "/claims", cl, prefer="return=minimal")
        if di:
            api(env, "POST", "/dishes", di, prefer="return=minimal")
        n_claims += len(cl)
        n_dishes += len(di)
        print(f"  ✓ {name[:34]:<36}{'新建' if created else '更新'}"
              f"　结论{len(cl)}　菜品{len(di)}")

    api(env, "PATCH", f"/extraction_runs?id=eq.{run['id']}",
        {"finished_at": "now()"}, prefer="return=minimal")

    print(f"\n完成：{len(pairs)} 家店（新建 {n_new}，更新 {len(pairs)-n_new}）"
          f"，{n_claims} 条结论，{n_dishes} 道菜品。")


if __name__ == "__main__":
    main()
