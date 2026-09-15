#!/usr/bin/env python3
"""把一个「粘贴文件」批量转成 samples/*.json。

Places API 因支付受阻放弃后，这是唯一的数据入口：从 Google 地图手动复制评论，
集中粘贴进一个文件，由脚本切分成标准输入，不必逐店手建 JSON。

用法：
    python3 pipeline/paste2json.py pipeline/samples/_paste.txt
    python3 pipeline/paste2json.py --dry-run pipeline/samples/_paste.txt   # 只看解析结果

粘贴文件有两种格式，按整份文件里有没有单独一行的 `---` 自动判断：

  分隔线格式                         编号格式
    === 店名 ===                       === 任意占位文字 ===
    人均：20-40                        一：
    区：Haymarket                      真实店名
    第一条评论（可跨多行）              人均：20-40
    ---                                区：Haymarket
    第二条评论                          第一条评论
                                       评论正文（可跨多行）
                                       第二条评论
                                       评论正文

「人均」「区」两行可选，且必须写在第一条评论之前。评论里也可能有
「人均：50 刀」这样的句子，只认店头的，免得把评论误当成店铺信息。
人均写法：20-40、A$20–40、$20~40、100+、30 都行；不知道就不写。

已存在的店不会被整个覆盖：保留文件里已有的 manual / places 信息，只更新评论。
评论和原来不一样时会提醒——那家店卡片里的「原句」可能对不上了，需要重跑提炼。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "pipeline", "samples")

BLOCK = re.compile(r"^\s*={3,}\s*(.+?)\s*={3,}\s*$")
DASH = re.compile(r"^\s*-{3,}\s*$")
# 「一：」「12:」这类纯编号行
INDEX = re.compile(r"^\s*[一二三四五六七八九十百千\d]+\s*[：:]\s*$")
# 「第一条评论」「第3条评论。」——允许后面跟模板残留文字，但整行不能太长
NTH = re.compile(r"^\s*第[一二三四五六七八九十\d]+条评论")
META = re.compile(r"^\s*(人均|区)\s*[：:]\s*(.*?)\s*$")


def slug(name):
    """店名 -> 安全的文件名。"""
    return re.sub(r"[^\w一-鿿]+", "", name) or "store"


def parse_price(text):
    """「A$20–40」→ (20, 40)；「100+」→ (100, None)；「30」→ (30, 30)；空 → (None, None)。

    看不懂或写反了（40-20）抛 ValueError，不去猜也不悄悄调换。
    数据库有同样的约束，在这里先拦下是因为这里的报错更好懂。
    """
    raw = (text or "").strip()
    t = re.sub(r"[^\d+\-–—~～至到]", "", raw)
    if not raw:
        return None, None
    if not re.search(r"\d", t):
        raise ValueError(f"人均「{raw}」不是金额。Google 显示「$$」这种是价位档次，"
                         f"请填具体数字（如 20-40），查不到就留空")
    m = re.fullmatch(r"(\d+)\+", t)
    if m:
        return int(m.group(1)), None
    m = re.fullmatch(r"(\d+)[\-–—~～至到](\d+)", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            raise ValueError(f"人均「{raw}」上限比下限小，是不是写反了")
        return lo, hi
    m = re.fullmatch(r"(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(1))
    raise ValueError(f"看不懂人均「{raw}」，请写成 20-40、100+ 或 30 这样")


def fmt_price(lo, hi):
    if lo is None:
        return ""
    if hi is None:
        return f"A${lo}+"
    return f"A${lo}" if hi == lo else f"A${lo}–{hi}"


def to_manual(meta_raw):
    """店头的「人均」「区」→ manual 块。写法有误时返回错误，不猜。"""
    manual, errs = {}, []
    if meta_raw.get("人均"):
        try:
            lo, hi = parse_price(meta_raw["人均"])
            manual["price_min"], manual["price_max"] = lo, hi
        except ValueError as e:
            errs.append(str(e))
    if meta_raw.get("区"):
        manual["suburb"] = meta_raw["区"]
    return manual, errs


def _finish(chunks):
    out = [("\n".join(c)).strip() for c in chunks]
    return [r for r in out if r]


def parse(text):
    """→ [(店名, [评论...], {"人均": ..., "区": ...}), ...]"""
    lines = text.splitlines()
    use_dash = any(DASH.match(l) for l in lines)

    stores = []
    name, chunks, pending, meta, started = None, [], False, {}, False
    for line in lines:
        m = BLOCK.match(line)
        if m:
            if name is not None:
                stores.append((name, _finish(chunks), meta))
            # 分隔线格式下 === 里就是店名；编号格式下它是占位符，店名在块内第一行
            name = m.group(1) if use_dash else None
            chunks, pending, meta, started = [[]], not use_dash, {}, False
            continue
        if name is None and not pending:
            continue
        if not use_dash and INDEX.match(line):
            continue
        if pending:
            if line.strip():
                name, pending = line.strip(), False
            continue
        mm = META.match(line)
        if mm and not started:
            meta[mm.group(1)] = mm.group(2)
            continue
        if use_dash and DASH.match(line):
            chunks.append([])
            continue
        if not use_dash and NTH.match(line) and len(line.strip()) < 40:
            chunks.append([])
            continue
        chunks[-1].append(line)
        if line.strip():
            started = True
    if name is not None:
        stores.append((name, _finish(chunks), meta))
    return stores


def existing_by_name():
    """samples/ 里已有的店：店名 → 文件路径。

    先按店名找现有文件再退回 slug()：有几个文件当初是手动改过名的
    （KobeWagyu、Hansang_Haymarket），slug() 复现不出来，只按 slug 命名会建出重复文件。
    """
    out = {}
    for p in sorted(os.listdir(SAMPLES)):
        if p.endswith(".json") and not p.startswith("_"):
            path = os.path.join(SAMPLES, p)
            out[json.load(open(path, encoding="utf-8"))["name"]] = path
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    files = [a for a in args if not a.startswith("--")]
    if not files:
        sys.exit(__doc__)
    stores = parse(open(files[0], encoding="utf-8").read())
    if not stores:
        sys.exit("没解析出任何店。检查是否有 `=== 店名 ===` 这样的行。")

    known = existing_by_name()
    bad, stale, empty = [], [], []
    for name, reviews, meta_raw in stores:
        manual, errs = to_manual(meta_raw)
        if errs:
            bad.append((name, errs))   # 整家跳过，改好再跑，免得半对半错地写进去
            continue
        path = known.get(name) or os.path.join(SAMPLES, slug(name) + ".json")
        exists = os.path.exists(path)
        if not exists and not reviews:
            empty.append(name)
            continue

        record = {"name": name, "reviews": reviews}
        if exists:
            record = json.load(open(path, encoding="utf-8"))
            if reviews and reviews != record.get("reviews"):
                record["reviews"] = reviews
                stale.append(name)
        if manual:
            record.setdefault("manual", {}).update(manual)

        m = record.get("manual") or {}
        info = [x for x in (fmt_price(m.get("price_min"), m.get("price_max")),
                            m.get("suburb") or "") if x]
        n = len(record["reviews"])
        print(f"  {n} 条  {'更新' if exists else '新建'}  {os.path.relpath(path, ROOT)}"
              + (f"  {' · '.join(info)}" if info else "")
              + ("  ⚠ 少于 3 条评论" if n < 3 else ""))
        if not dry:
            json.dump(record, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\n共 {len(stores)} 家店" + ("　（dry-run，没写文件）" if dry else ""))
    if stale:
        print("\n⚠ 这几家的评论和原文件不同，已换成新的：" + "、".join(stale))
        print("  它们卡片里的「原句」可能对不上了，要重跑提炼：python3 pipeline/run_all.py")
    if empty:
        print("\n⚠ 这几家是新店但没有评论，跳过：" + "、".join(empty))
    if bad:
        print("\n✗ 这几家的写法有问题，整家没写入，改好再跑一次：")
        for name, errs in bad:
            for e in errs:
                print(f"  {name}：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
