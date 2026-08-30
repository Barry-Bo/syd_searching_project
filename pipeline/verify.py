#!/usr/bin/env python3
"""校验一张卡片是否忠于原始评论。

用法：python3 pipeline/verify.py pipeline/samples/xxx.json pipeline/out/xxx__v2__模型.json

检查四件事：
  1. 每个「原句」是否在评论里逐字存在（防幻觉）
  2. 「提及」是否等于「评论编号」的长度（防虚报次数）
  3. 「评论编号」指向的评论是否真的包含该内容（防张冠李戴）
  4. 「必点」是否抽成了品类词而非具体菜品
"""
import json
import re
import sys

CATEGORY_WORDS = {"stews", "stew", "soups", "soup", "dishes", "dish", "side dishes",
                  "food", "mains", "noodles", "banchan", "side dish", "general dishes"}


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src = json.load(open(sys.argv[1], encoding="utf-8"))
    card = json.load(open(sys.argv[2], encoding="utf-8"))
    reviews = src["reviews"]
    blob = norm("\n".join(reviews))

    fails, checks = [], 0

    for field in ("适合", "慎选", "必点"):
        for item in card.get(field) or []:
            nums_ = item.get("评论编号") or []
            # 1. 原句逐字，且必须出自它自己引用的评论（防跨评论缝合 / 防虚报编号）
            if "原句" in item and item["原句"]:
                checks += 1
                q = norm(item["原句"])
                if q not in blob:
                    fails.append(f"[{field}] 原句不是逐字原文：{item['原句'][:60]}…")
                elif nums_:
                    cited = " ".join(norm(reviews[n - 1]) for n in nums_ if 1 <= n <= len(reviews))
                    if q not in cited:
                        fails.append(
                            f"[{field}] 原句在评论里存在，但不在它引用的评论 {nums_} 中"
                            f"（跨评论缝合或编号虚报）：{item['原句'][:50]}…")
                checks += 1
                if len(item["原句"].split()) > 40:
                    fails.append(f"[{field}] 原句超过 40 词，疑似拼接：{item['原句'][:50]}…")
            elif field == "适合":
                checks += 1
                fails.append(f"[适合] 缺少「原句」字段，结论无法核验：{item.get('人群或场合')}")
            # 2 & 3. 编号自洽 + 编号命中
            nums = item.get("评论编号")
            if nums is not None:
                checks += 1
                if item.get("提及") != len(nums):
                    fails.append(f"[{field}] 提及={item.get('提及')} 但编号有 {len(nums)} 个：{item}")
                bad = [n for n in nums if not (1 <= n <= len(reviews))]
                if bad:
                    fails.append(f"[{field}] 评论编号越界：{bad}")
                if field == "必点" and item.get("菜名"):
                    checks += 1
                    key = norm(item["菜名"]).split("(")[0].strip()
                    hit = any(key in norm(reviews[n - 1]) for n in nums if 1 <= n <= len(reviews))
                    if not hit and len(key) > 3:
                        fails.append(f"[必点] 「{item['菜名']}」在它引用的评论 {nums} 里找不到")
            # 4. 品类词
            if field == "必点" and item.get("菜名"):
                checks += 1
                if norm(item["菜名"]) in CATEGORY_WORDS:
                    fails.append(f"[必点] 「{item['菜名']}」是品类词不是菜品")

    print(f"共 {checks} 项检查，失败 {len(fails)} 项\n")
    for f in fails:
        print("  ✗", f)
    if not fails:
        print("  全部通过")
    print(f"\n通过率：{(checks - len(fails)) / checks * 100:.0f}%" if checks else "")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
