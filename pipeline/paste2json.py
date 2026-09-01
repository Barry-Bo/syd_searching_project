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

也兼容「编号格式」——分隔行内是占位符、店名单独成行、用「第N条评论」分隔：
    === 任意占位文字 ===
    一：
    真实店名
    第一条评论
    评论正文（可跨多行）
    第二条评论
    评论正文
脚本按整份文件里有没有 `---` 自动判断用哪种解析方式。
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


BLOCK = re.compile(r"^\s*={3,}\s*(.+?)\s*={3,}\s*$")
DASH = re.compile(r"^\s*-{3,}\s*$")
# 「一：」「12:」这类纯编号行
INDEX = re.compile(r"^\s*[一二三四五六七八九十百千\d]+\s*[：:]\s*$")
# 「第一条评论」「第3条评论。」——允许后面跟模板残留文字，但整行不能太长
NTH = re.compile(r"^\s*第[一二三四五六七八九十\d]+条评论")


def _finish(chunks):
    out = [("\n".join(c)).strip() for c in chunks]
    return [r for r in out if r]


def parse(text):
    """自动判断格式。整份文件里出现过 `---` 就用它，否则用「第N条评论」。"""
    lines = text.splitlines()
    use_dash = any(DASH.match(l) for l in lines)

    stores, name, chunks, pending = [], None, [], False
    for line in lines:
        m = BLOCK.match(line)
        if m:
            if name is not None:
                stores.append((name, chunks))
            # 分隔行里的文字只在 --- 格式下当店名；编号格式下等块内第一行
            name = m.group(1) if use_dash else None
            chunks, pending = [[]], not use_dash
            continue
        if name is None and not pending:
            continue
        if use_dash:
            if DASH.match(line):
                chunks.append([])
            else:
                chunks[-1].append(line)
            continue
        # 编号格式
        if INDEX.match(line):
            continue
        if pending:
            if line.strip():
                name, pending = line.strip(), False
            continue
        if NTH.match(line) and len(line.strip()) < 40:
            chunks.append([])
        else:
            chunks[-1].append(line)
    if name is not None:
        stores.append((name, chunks))

    return [(n, _finish(c)) for n, c in stores]


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
