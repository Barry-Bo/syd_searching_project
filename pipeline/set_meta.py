#!/usr/bin/env python3
"""给已有的店补「人均」和「区」，不动评论。

用法：
    python3 pipeline/set_meta.py --dry-run pipeline/samples/_meta.txt   # 先看一眼
    python3 pipeline/set_meta.py pipeline/samples/_meta.txt

文件格式和粘贴文件的店头一样：
    === 店名 ===
    人均：20-40
    区：Haymarket

店名必须和 samples/ 里的完全一致——_meta.txt 是照着现有店名生成的，照着填即可。
没填的店直接跳过，不会清空已有的值。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paste2json import BLOCK, META, ROOT, existing_by_name, fmt_price, to_manual  # noqa: E402


def parse(text):
    out, name, meta = [], None, {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = BLOCK.match(line)
        if m:
            if name:
                out.append((name, meta))
            name, meta = m.group(1), {}
            continue
        mm = META.match(line)
        if name and mm and mm.group(2):
            meta[mm.group(1)] = mm.group(2)
    if name:
        out.append((name, meta))
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    files = [a for a in args if not a.startswith("--")]
    if not files:
        sys.exit(__doc__)
    entries = parse(open(files[0], encoding="utf-8").read())
    known = existing_by_name()

    done, blank, unknown, bad = 0, [], [], []
    for name, meta_raw in entries:
        if not meta_raw:
            blank.append(name)
            continue
        path = known.get(name)
        if not path:
            unknown.append(name)
            continue
        manual, errs = to_manual(meta_raw)
        if errs:
            bad.append((name, errs))
            continue
        record = json.load(open(path, encoding="utf-8"))
        record.setdefault("manual", {}).update(manual)
        m = record["manual"]
        info = [x for x in (fmt_price(m.get("price_min"), m.get("price_max")),
                            m.get("suburb") or "") if x]
        print(f"  ✓ {name[:36]:<38}{' · '.join(info)}")
        done += 1
        if not dry:
            json.dump(record, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\n已填 {done} 家 / 共 {len(entries)} 家" + ("　（dry-run，没写文件）" if dry else ""))
    if blank:
        print(f"还没填的 {len(blank)} 家：" + "、".join(n[:18] for n in blank))
    if unknown:
        print("\n⚠ 店名在 samples/ 里找不到（是不是改了店名）：" + "、".join(unknown))
    if bad:
        print("\n✗ 写法有问题，没写入：")
        for name, errs in bad:
            for e in errs:
                print(f"  {name}：{e}")
        sys.exit(1)
    if done and not dry:
        print("\n下一步：python3 pipeline/load_db.py　把人均和区写进数据库")


if __name__ == "__main__":
    main()
