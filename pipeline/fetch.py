#!/usr/bin/env python3
"""从 Google Places API 拉店铺信息与评论，写成 samples/*.json。

用法：
    python3 pipeline/fetch.py "Henry Lee's, Haymarket"        # 新店，拉全套
    python3 pipeline/fetch.py --dry-run "Fireside, Sydney"    # 只看不写
    python3 pipeline/fetch.py --refresh                       # 给已有的店补结构化字段
    python3 pipeline/fetch.py --refresh --with-reviews        # 连评论一起换成 API 版

只用标准库。计划里第 1 周就该有这个脚本，因为 Google Cloud 支付验证卡住，
当时降级成了 paste2json.py 的手动通道。现在它回来了，但**不推翻手动通道的产物**
——见下面第 2 条。

四个实现决策：

1. **两步调用，且第一步只要 id。** Text Search 的 field mask 只写 `places.id`，
   落在 Essentials (IDs Only) 档，免费且无上限；拿到 place_id 后再用 Place Details
   取全字段。反过来做——Text Search 直接要全字段——同样的结果要 $32-40/1000。
   150 家店就是 $0 和 $6 的差别。计费按「请求里最贵的那个字段」算，所以 field mask
   不是优化技巧，是计费开关。

2. **--refresh 默认不动已有评论。** samples/ 里那 23 家店的评论是手动复制的，
   现有的 v5 卡片和 verify.py 的校验全都建立在这批原文上。API 返回的 5 条大概率
   不是同一批（排序会变），一旦覆盖，卡片里的「原句」在评论里就找不到了，
   23 张卡会集体校验失败。所以默认只补 places 结构化字段，评论原样保留。
   真要换用 --with-reviews，脚本会提醒你必须重跑提炼。

3. **评论取 originalText 而不是 text。** Google 会按请求语言把评论翻译一遍，
   `text` 是译文，`originalText` 才是用户写下的原文。整个产品的可信度建立在
   「原句可回 Google 逐字核对」上，存译文等于自断根基。

4. **写进已有 JSON 的 places 块，不改动顶层结构。** 顶层仍是 {"name", "reviews"}，
   extract.py / run_all.py / verify.py 一行都不用改；结构化字段放在 places 块里，
   由 load_db.py 读出来填 restaurants 表。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import ROOT, load_env  # noqa: E402

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAIL_URL = "https://places.googleapis.com/v1/places/"

# Place Details 的 field mask。按 SKU 档位分组写，改动时能一眼看出会不会变贵。
DETAIL_FIELDS = ",".join([
    # Essentials(IDs Only)：photos 的引用串
    "id", "photos",
    # Essentials
    "formattedAddress", "shortFormattedAddress", "location",
    # Pro
    "displayName", "addressComponents", "primaryTypeDisplayName", "types",
    # Enterprise —— 朋友 C 要的价位、受访者 03 要的营业时间在这档
    "rating", "userRatingCount", "priceLevel", "regularOpeningHours",
    # Enterprise + Atmosphere —— 评论和朋友 F 要的那几项在这档，整次请求按它计费
    "reviews", "takeout", "delivery", "goodForChildren", "allowsDogs",
])

# priceLevel 是枚举字符串，schema 里是 0-4 的 smallint
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    "PRICE_LEVEL_UNSPECIFIED": None,
}

# 悉尼 CBD，用来把搜索结果偏向本地。同名店在别的城市也有，不加这个会搜错。
SYDNEY = {"circle": {"center": {"latitude": -33.8688, "longitude": 151.2093},
                     "radius": 40000.0}}


def slug(name):
    """和 paste2json.py 保持同一套规则，否则重新拉取会生成一批新文件。"""
    return re.sub(r"[^\w一-鿿]+", "", name) or "store"


def _req(url, key, field_mask, body=None):
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": field_mask,
               "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def search_id(key, query):
    """店名 → place_id。field mask 只要 id，落在免费档。"""
    res = _req(SEARCH_URL, key, "places.id", {
        "textQuery": query,
        "maxResultCount": 1,
        "regionCode": "AU",
        "locationBias": SYDNEY,
    })
    places = res.get("places") or []
    return places[0]["id"] if places else None


def detail(key, place_id):
    """place_id → 全部字段。这次请求按 Enterprise + Atmosphere 计费。"""
    return _req(DETAIL_URL + urllib.parse.quote(place_id), key, DETAIL_FIELDS)


def suburb_of(d):
    """从 addressComponents 里取 locality —— 澳洲的 suburb 落在这个类型上。"""
    for c in d.get("addressComponents") or []:
        if "locality" in c.get("types", []):
            return c.get("longText")
    return None


def to_places_block(d):
    """Place Details 响应 → 存进 samples/*.json 的 places 块。

    字段名直接用 restaurants 表的列名，load_db.py 就不必再做一次映射。
    """
    hours = d.get("regularOpeningHours") or {}
    return {
        "place_id": d.get("id"),
        "display_name": (d.get("displayName") or {}).get("text"),
        "address": d.get("shortFormattedAddress") or d.get("formattedAddress"),
        "suburb": suburb_of(d),
        "lat": (d.get("location") or {}).get("latitude"),
        "lng": (d.get("location") or {}).get("longitude"),
        "rating": d.get("rating"),
        "user_ratings_total": d.get("userRatingCount"),
        "price_level": PRICE_LEVELS.get(d.get("priceLevel")),
        "cuisine": (d.get("primaryTypeDisplayName") or {}).get("text"),
        "takeout": d.get("takeout"),
        "delivery": d.get("delivery"),
        "good_for_children": d.get("goodForChildren"),
        "allows_dogs": d.get("allowsDogs"),
        "opening_hours": {"weekday_descriptions": hours.get("weekdayDescriptions")}
                         if hours.get("weekdayDescriptions") else None,
        "photo_refs": [p["name"] for p in (d.get("photos") or [])],
        "fetched_at": None,  # 由调用方填，避免这里引入 datetime 依赖之外的歧义
    }


def reviews_of(d):
    """取原文而非译文。没有 originalText 的（本来就是英文）退回 text。"""
    out = []
    for r in d.get("reviews") or []:
        t = (r.get("originalText") or {}).get("text") or (r.get("text") or {}).get("text")
        if t and t.strip():
            out.append(t.strip())
    return out


def existing_names():
    """samples/ 下已有的店：文件名 → 店名。"""
    out = {}
    for p in sorted(os.listdir(os.path.join(ROOT, "pipeline", "samples"))):
        if not p.endswith(".json") or p.startswith("_"):
            continue
        path = os.path.join(ROOT, "pipeline", "samples", p)
        out[path] = json.load(open(path, encoding="utf-8"))["name"]
    return out


def fetch_one(key, query):
    pid = search_id(key, query)
    if not pid:
        return None, None
    d = detail(key, pid)
    return d, to_places_block(d)


def main():
    import datetime
    args = [a for a in sys.argv[1:]]
    dry = "--dry-run" in args
    refresh = "--refresh" in args
    with_reviews = "--with-reviews" in args
    queries = [a for a in args if not a.startswith("--")]

    key = load_env().get("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit(".env.local 里 GOOGLE_PLACES_API_KEY 是空的。"
                 "先跑 check_places.py 确认 key 可用。")

    if refresh:
        targets = list(existing_names().items())           # [(path, name)]
    elif queries:
        targets = [(None, q) for q in queries]
    else:
        sys.exit(__doc__)

    if refresh and with_reviews:
        print("⚠ --with-reviews 会用 API 返回的评论覆盖手动复制的原文。")
        print("  现有 23 张 v5 卡片的「原句」将在新评论里找不到，verify.py 会集体失败。")
        print("  覆盖后必须重跑：python3 pipeline/run_all.py\n")

    n_detail = 0
    for path, name in targets:
        print(f"  {name[:38]:<40}", end="", flush=True)
        try:
            d, block = fetch_one(key, name if refresh else name)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print(f"✗ HTTP {e.code}　{body[:120]}")
            continue
        except urllib.error.URLError as e:
            print(f"✗ 连不上：{e.reason}")
            continue
        if not d:
            print("✗ 搜不到这家店")
            continue
        n_detail += 1
        block["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        revs = reviews_of(d)

        if path is None:
            # 先按店名找现有文件再退回 slug()：samples/ 里有两个文件当初是手动改过名的
            # （Hansang_Haymarket、KobeWagyu），slug() 复现不出来。只按 slug 命名的话，
            # 命令行传这两家店会新建文件，和已有的并存变成重复数据。
            path = next((p for p, n in existing_names().items() if n == name), None) \
                or os.path.join(ROOT, "pipeline", "samples", slug(name) + ".json")
        record = {"name": name, "reviews": revs}
        if os.path.exists(path):
            record = json.load(open(path, encoding="utf-8"))
            if with_reviews:
                record["reviews"] = revs
        record["places"] = block

        flags = []
        if block["price_level"] is not None:
            flags.append(f"价位{block['price_level']}")
        if block["photo_refs"]:
            flags.append(f"图{len(block['photo_refs'])}")
        if block["takeout"] is not None:
            flags.append("外卖" + ("有" if block["takeout"] else "无"))
        print(f"{block['suburb'] or '?':<12}{block['rating'] or '?':<5}"
              f"评论{len(revs)}　{'　'.join(flags)}")

        if not dry:
            json.dump(record, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)

    print(f"\n{'（dry-run，没写文件）' if dry else '已写入 samples/'}"
          f"　Place Details 调用 {n_detail} 次"
          f"（Ent+Atmosphere 档，每月前 5000 次免费）")
    if not dry and n_detail:
        print("下一步：python3 pipeline/load_db.py　把结构化字段写进 restaurants 表")


if __name__ == "__main__":
    main()
