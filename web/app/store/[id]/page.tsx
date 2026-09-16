import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getRestaurant, warnings, fits, dishes, priceText, mapsUrl, card,
} from "@/lib/data";
import { SCENES, type Claim } from "@/lib/types";

const NA = <span className="na">评论未提及</span>;

function Item({ c, total }: { c: Claim; total: number }) {
  return (
    <li>
      <p className="claim">
        <strong>{c.subject}</strong>
        {c.reason && <span className="why">{c.reason}</span>}
        <span className="cite" title={`依据来自第 ${c.review_nums.join("、")} 条评论`}>
          {c.mentions}/{total}
        </span>
      </p>
      {c.quote && <blockquote>{c.quote}</blockquote>}
    </li>
  );
}

// 用显式的 Promise 类型而不是 PageProps<"/store/[id]">：
// 后者依赖 next dev/build 生成的路由类型，新建路由后没重新生成就会报错。
// 官方文档给的就是这种写法，不依赖生成物。
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const r = await getRestaurant(id);
  if (!r) notFound();

  const c = card(r);
  const total = c?.review_count ?? 0;
  const ws = warnings(r);
  const strong = ws.filter((w) => w.mentions >= 2);
  const weak = ws.filter((w) => w.mentions === 1);
  const vibe = c?.vibe ?? [];
  const speed = vibe.includes("上菜快") ? "快" : vibe.includes("上菜慢") ? "慢" : null;
  const mood = ["安静", "嘈杂", "空间宽敞", "座位拥挤", "适合久坐"].find((v) => vibe.includes(v));

  // 每家店固定五格，缺的显式写出来——用户要能分清「数据没有」和「我漏了」
  const glance: [string, React.ReactNode][] = [
    ["人均", priceText(r) ?? NA],
    ["上菜速度", speed ?? NA],
    ["氛围", mood ?? NA],
    ["是否需排队", vibe.includes("需排队") ? "需排队" : NA],
    ["评论一致性", c?.consistency ?? "—"],
  ];

  return (
    <main className="wrap">
      <Link href="/" className="back">← 返回列表</Link>

      <article className="detail">
        <header className="dh">
          <h1>{r.name}</h1>
          <div className="tags">
            {(c?.scene_tags ?? []).map((t) => (
              <span key={t} className="tag">{SCENES[t] ?? t}</span>
            ))}
            {!(c?.scene_tags ?? []).length && (
              <span className="tag dim">评论中无场合线索</span>
            )}
            {vibe.map((v) => <span key={v} className="tag">{v}</span>)}
          </div>
        </header>

        <div className="glance">
          {glance.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </div>

        <section className="sec warn">
          <h3>慎选</h3>
          {strong.length ? (
            <ul className="items">
              {strong.map((w, i) => <Item key={i} c={w} total={total} />)}
            </ul>
          ) : (
            <p className="none">
              这 {total} 条评论里，没有两人以上共同提到的问题。
              <br />
              但只有 {total} 条评论——没人提到，不等于这家店没有问题。
            </p>
          )}
        </section>

        {weak.length > 0 && (
          <section className="sec mention">
            <h3>有人提到</h3>
            <p className="hint">
              下面每条都只有 1 个人说过。不是共识，可能是个人体验，也可能是别人没碰上。
              看原句里他具体遇到了什么，再决定要不要在意。
            </p>
            <ul className="items">
              {weak.map((w, i) => <Item key={i} c={w} total={total} />)}
            </ul>
          </section>
        )}

        <section className="sec pick">
          <h3>必点</h3>
          {dishes(r).length ? (
            <ul className="items">
              {dishes(r).map((d, i) => (
                <li key={i}>
                  <p className="claim">
                    <strong>{d.name_raw}</strong>
                    <span className="cite" title={`第 ${d.review_nums.join("、")} 条评论`}>
                      {d.mentions}/{total}
                    </span>
                  </p>
                  {d.quote && <blockquote>{d.quote}</blockquote>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="none">没有被明确称赞的具体菜品。</p>
          )}
        </section>

        <section className="sec">
          <h3>适合</h3>
          {fits(r).length ? (
            <ul className="items">
              {fits(r).map((f, i) => <Item key={i} c={f} total={total} />)}
            </ul>
          ) : (
            <p className="none">评论里没有明确的场合线索。</p>
          )}
        </section>

        <section className="sec">
          <h3>高频负面词</h3>
          {(c?.negative_words ?? []).length ? (
            <div className="negs">
              {c!.negative_words.map((n) => <span key={n} className="neg">{n}</span>)}
            </div>
          ) : (
            <p className="none">{NA}</p>
          )}
        </section>

        <a className="maps" href={mapsUrl(r)} target="_blank" rel="noopener noreferrer">
          在 Google 地图打开（照片、地址、营业时间、导航）
        </a>
      </article>

      <p className="foot">
        数据来源：Google 地图公开评论，每家取默认排序的前 {total} 条，未经人工挑选。
        卡片由大语言模型自动提炼，未经人工编辑。
      </p>
    </main>
  );
}
