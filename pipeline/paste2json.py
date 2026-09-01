#!/usr/bin/env python3
"""把一个「粘贴文件」批量转成 samples/*.json。

Places API 接入受阻时的降级通道：手动复制评论，但只复制一次、集中粘贴，
由脚本切分成标准输入文件，不必逐店手工建 JSON。

用法：
    python3 pipeline/paste2json.py pipeline/samples/_paste.txt

粘贴文件格式：
    === 店名 ===
    第一条评论（可跨多行）
    ---
    第二条评论
    ---
    第三条评论

    === 下一家店名 ===
    ...

规则：`=== 名字 ===` 开一家新店，单独一行的 `---` 分隔评论。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slug(name):
    """店名 -> 安全的文件名。"""
    s = re.sub(r"[^\w一-鿿]+", "", name)
    return s or "store"


def parse(text):
    stores, name, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^\s*={3,}\s*(.+?)\s*={3,}\s*$", line)
        if m:
            if name:
                stores.append((name, buf))
            name, buf = m.group(1), [[]]
        elif re.match(r"^\s*-{3,}\s*$", line):
            if name:
                buf.append([])
        elif name is not None:
            buf[-1].append(line)
    if name:
        stores.append((name, buf))

    out = []
    for name, chunks in stores:
        reviews = [("\n".join(c)).strip() for c in chunks]
        out.append((name, [r for r in reviews if r]))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    text = open(sys.argv[1], encoding="utf-8").read()
    stores = parse(text)
    if not stores:
        sys.exit("没解析出任何店。检查是否有 `=== 店名 ===` 这样的行。")

    outdir = os.path.join(ROOT, "pipeline", "samples")
    for name, reviews in stores:
        path = os.path.join(outdir, slug(name) + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": name, "reviews": reviews}, f,
                      ensure_ascii=False, indent=2)
        warn = "  ⚠ 少于 3 条，信息可能不足" if len(reviews) < 3 else ""
        print(f"  {len(reviews)} 条  {os.path.relpath(path, ROOT)}{warn}")
    print(f"\n共 {len(stores)} 家店，{sum(len(r) for _, r in stores)} 条评论")


if __name__ == "__main__":
    main()
