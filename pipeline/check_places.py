#!/usr/bin/env python3
"""验证 Google Places API 是否真的可用，并把失败原因指到具体那一步。

用法：python3 pipeline/check_places.py

只用标准库，只花两次调用（都在免费额度内）。

为什么单独写这个：Places API 的失败几乎全部返回 403，但背后是四件完全不同的事——
key 抄错了、API 没启用、账单没绑、key 的 API 限制没勾。Google 的报错正文里写了
区别，但混在一大段 JSON 里不容易看见。这个脚本把它们分开，直接告诉你去点哪里。

两步分开测也是有意的：
  第 1 步 Text Search 只要 places.id —— 落在 Essentials (IDs Only) 档，免费无上限。
          它能验证 key 有效 + API 已启用，且不需要账单额度。
  第 2 步 Place Details 取全字段 —— 落在 Enterprise + Atmosphere 档（$25/1000，
          每月前 5000 次免费）。它才会碰到账单校验。
所以「第 1 步过、第 2 步挂」= 账单问题；「第 1 步就挂」= key 或 API 启用问题。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import DETAIL_FIELDS, PRICE_LEVELS, detail, search_id  # noqa: E402

# 拿一家已经在 samples/ 里的店做探针，方便和手动通道的数据对照
PROBE = "Henry Lee's, Haymarket, Sydney"


def diagnose(err):
    """把 Google 的报错正文翻成「去点哪里」。"""
    t = err.lower()
    if "api key not valid" in t or "api_key_invalid" in t:
        return ("key 本身无效",
                "多半是抄漏了字符，或者删掉过又重建。回 Credentials 页面重新复制，"
                "注意别把前后空格带进 .env.local")
    if "has not been used in project" in t or "service_disabled" in t:
        return ("Places API (New) 没启用",
                "APIs & Services → Library → 搜 Places API (New) → Enable。"
                "注意要选带 (New) 的那个，旧版是另一个服务，启用了也没用")
    if "billing" in t:
        return ("项目没绑账单账户",
                "Billing → Link a billing account。免费额度也要求先绑卡才能用")
    if "referer" in t or "ip address" in t or "referrer" in t:
        return ("key 设了来源限制，本地脚本发不出去",
                "Credentials → 点这个 key → Application restrictions 改成 None")
    if "blocked" in t or "permission_denied" in t or "consumer" in t:
        return ("key 的 API 限制里没勾 Places API (New)",
                "Credentials → 点这个 key → API restrictions → 勾上 Places API (New)")
    if "resource_exhausted" in t or "quota" in t:
        return ("撞到配额上限",
                "Google Maps Platform → Quotas，把每日上限调高（或等明天）")
    return ("未识别的错误", "把上面这段原文贴出来")


def step(n, title, fn):
    print(f"  [{n}] {title} …", end="", flush=True)
    try:
        result = fn()
        print(" ✓")
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f" ✗ HTTP {e.code}")
        cause, fix = diagnose(body)
        print(f"\n      原因：{cause}\n      怎么修：{fix}\n")
        print("      Google 原文：")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        print("      " + msg[:400].replace("\n", "\n      "))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f" ✗ 连不上：{e.reason}")
        sys.exit(1)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from extract import load_env
    key = load_env().get("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit(".env.local 里 GOOGLE_PLACES_API_KEY 是空的")

    print(f"探针店：{PROBE}\n")

    pid = step(1, "Text Search（免费档，验 key + API 启用）",
               lambda: search_id(key, PROBE))
    print(f"      place_id = {pid}\n")

    d = step(2, "Place Details（付费档，验账单额度）",
             lambda: detail(key, pid))

    print("\n拿到的字段——这些正是用户反馈里缺的那几项：\n")
    rows = [
        ("店名", d.get("displayName", {}).get("text")),
        ("地址", d.get("shortFormattedAddress") or d.get("formattedAddress")),
        ("评分", f"{d.get('rating')}（{d.get('userRatingCount')} 人评价）"),
        ("价位", f"{d.get('priceLevel')} → price_level={PRICE_LEVELS.get(d.get('priceLevel'))}"
                 "　← 朋友 C「我最好奇的价位你没标注」"),
        ("评论", f"{len(d.get('reviews') or [])} 条"),
        ("照片", f"{len(d.get('photos') or [])} 张　← 朋友 D「有图片就更好了」"),
        ("外卖", f"takeout={d.get('takeout')} delivery={d.get('delivery')}"
                 "　← 朋友 F「外卖支持与否」"),
        ("儿童宠物", f"good_for_children={d.get('goodForChildren')} "
                     f"allows_dogs={d.get('allowsDogs')}　← 朋友 F"),
        ("营业时间", "有" if d.get("regularOpeningHours") else "无"),
    ]
    for k, v in rows:
        print(f"  {k:<10}{v}")

    print(f"\n本次消耗：Text Search(IDs Only) 1 次（免费无上限）"
          f" + Place Details(Ent+Atmosphere) 1 次（每月前 5000 次免费）")
    print("\n全部通过。可以跑 fetch.py 了。")


if __name__ == "__main__":
    main()
