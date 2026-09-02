#!/usr/bin/env python3
"""把 out/ 里的卡片渲染成一个可分享的网页，用于用户测试。

用法：
    python3 pipeline/render_cards.py                    # 默认 v5
    python3 pipeline/render_cards.py --prompt v5 --out /tmp/cards.html

模板在 pipeline/card_template.html，用 __N__ / __CARDS__ / __NAMES__ 三个占位符。
不用 str.format，因为模板里全是 CSS 大括号。

呈现上的三个决策来自第 1 周 Gate 的用户反馈（见 research/gate-feedback.md）：
  1. 「慎选」按提及人数分层——≥2 人为共识，1 人降级为「有人提到」。
     用户原话：「你的评论很多都是 1/5，那是信还是不信啊」。
     分层本身就是产品替用户做的那一层判断。
  2. 评论原句默认隐藏，顶部开关展开。原句是证据不是正文，
     默认阅读保持纯中文，避免中英夹杂。
  3. 每张卡固定五格骨架，缺的显式写「评论未提及」「待接入」，
     让两家店能横向比较，也让用户知道是数据没有而不是我漏了。
"""
import glob
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENE = {"date": "约会", "friends": "朋友聚餐", "family": "家庭", "solo": "一人食"}
NA = '<span class="na">评论未提及</span>'


def e(x):
    return html.escape(str(x))


def nm(it):
    return it.get("提及") or 0


def cite(it, total):
    ns = it.get("评论编号") or []
    return (f'<span class="cite" title="依据来自第 {", ".join(map(str, ns))} 条评论">'
            f'{nm(it)}<span class="sl">/</span>{total}</span>')


def quote(it):
    q = it.get("原句")
    return f'<blockquote>{e(q)}</blockquote>' if q else ''


def glance(c):
    """固定五格骨架。缺的显式标注，不留空。"""
    v = c.get("vibe") or []
    speed = "快" if "上菜快" in v else ("慢" if "上菜慢" in v else None)
    mood = next((x for x in ("安静", "嘈杂", "空间宽敞", "座位拥挤", "适合久坐") if x in v), None)
    queue = "需排队" if "需排队" in v else None
    return [("人均价位", '<span class="na pend">待接入</span>'),
            ("上菜速度", e(speed) if speed else NA),
            ("氛围", e(mood) if mood else NA),
            ("是否需排队", e(queue) if queue else NA),
            ("评论一致性", e(c.get("一致性") or "—"))]


def item(x, total, extra=""):
    key = x.get("提醒") or x.get("菜名") or x.get("人群或场合")
    why = x.get("原因") or x.get("依据")
    return (f'<li><p class="claim"><strong>{e(key)}</strong>'
            + (f'<span class="rs">{e(why)}</span>' if why else "")
            + extra + cite(x, total) + f'</p>{quote(x)}</li>')


def load(version):
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "pipeline", "samples", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        stem = os.path.splitext(os.path.basename(f))[0]
        hits = glob.glob(os.path.join(ROOT, "pipeline", "out", f"{stem}__{version}__*.json"))
        if not hits:
            continue
        s = json.load(open(f, encoding="utf-8"))
        out.append((s["name"], len(s["reviews"]),
                    json.load(open(hits[0], encoding="utf-8"))))
    return out


def render_card(i, name, total, c):
    sel = sorted(c.get("慎选") or [], key=nm, reverse=True)
    strong = [x for x in sel if nm(x) >= 2]
    weak = [x for x in sel if nm(x) == 1]
    must = sorted(c.get("必点") or [], key=nm, reverse=True)
    fit = sorted(c.get("适合") or [], key=nm, reverse=True)
    neg = c.get("高频负面词") or []
    scenes = [SCENE.get(x, x) for x in (c.get("场景标签") or [])]

    p = [f'<article class="card" id="c{i}"><header class="ch"><h2>{e(name)}</h2><div class="meta">',
         "".join(f'<span class="chip">{e(x)}</span>' for x in scenes)
         or '<span class="chip dim">评论中无场合线索</span>',
         '</div></header><div class="glance">',
         "".join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in glance(c)),
         '</div><section class="sec warn"><h3>慎选</h3>']

    p.append('<ul class="items">' + "".join(item(x, total) for x in strong) + '</ul>' if strong
             else '<p class="none">这 5 条评论里，没有两人以上共同提到的问题。</p>')
    p.append('</section>')

    if weak:
        p.append('<section class="sec mention"><h3>有人提到</h3>'
                 '<p class="hint">下面每条都只有 1 个人说过。不是共识，可能是个人体验，'
                 '也可能是别人没碰上。打开顶部「显示评论原文」看他具体遇到了什么，再决定要不要在意。</p>'
                 '<ul class="items">' + "".join(item(x, total) for x in weak) + '</ul></section>')

    p.append('<section class="sec pick"><h3>必点</h3>')
    p.append('<ul class="items">' + "".join(
        item(x, total, f'<span class="badge">{nm(x)} 人都夸</span>' if nm(x) >= 2 else "")
        for x in must) + '</ul>' if must else '<p class="none">没有被明确称赞的具体菜品。</p>')
    p.append('</section><section class="sec"><h3>适合</h3>')
    p.append('<ul class="items">' + "".join(item(x, total) for x in fit) + '</ul>' if fit
             else '<p class="none">评论里没有明确的场合线索。</p>')
    p.append('</section><section class="sec"><h3>高频负面词</h3>')
    p.append('<div class="tags">' + "".join(f'<span class="tag">{e(x)}</span>' for x in neg)
             + '</div>' if neg else f'<p class="none">{NA}</p>')
    p.append(f'</section><footer class="vote" data-i="{i}">'
             '<span class="q">这张卡对你选店有用吗？</span>'
             '<span class="btns"><button type="button" data-v="yes">有用</button>'
             '<button type="button" data-v="partly">一半一半</button>'
             '<button type="button" data-v="no">没用</button></span></footer></article>')
    return "".join(p)


def main():
    args = sys.argv[1:]
    version = args[args.index("--prompt") + 1] if "--prompt" in args else "v5"
    dest = args[args.index("--out") + 1] if "--out" in args else os.path.join(ROOT, "out-cards.html")

    cards = load(version)
    if not cards:
        sys.exit(f"pipeline/out/ 下没有 {version} 的结果，先跑 run_all.py")

    tpl = open(os.path.join(ROOT, "pipeline", "card_template.html"), encoding="utf-8").read()
    page = (tpl.replace("__CARDS__", "\n".join(render_card(i, *c) for i, c in enumerate(cards)))
               .replace("__NAMES__", json.dumps([n for n, _, _ in cards], ensure_ascii=False))
               .replace("__N__", str(len(cards))))
    for ph in ("__N__", "__CARDS__", "__NAMES__"):
        assert ph not in page, f"占位符 {ph} 未被替换"

    open(dest, "w", encoding="utf-8").write(page)
    strong = sum(1 for _, _, c in cards if [x for x in (c.get("慎选") or []) if nm(x) >= 2])
    weak = sum(1 for _, _, c in cards if [x for x in (c.get("慎选") or []) if nm(x) == 1])
    print(f"{len(cards)} 张卡 -> {dest}（{len(page):,} 字节）")
    print(f"  有「慎选」(≥2 人) 的店：{strong}/{len(cards)}")
    print(f"  有「有人提到」(1 人) 的店：{weak}/{len(cards)}")


if __name__ == "__main__":
    main()
