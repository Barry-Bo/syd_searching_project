import { Suspense } from "react";
import Link from "next/link";
import {
  getRestaurants, warnings, dishes, priceText, matches, card,
} from "@/lib/data";
import { SCENES, suburbLabel, type Restaurant } from "@/lib/types";

type Query = { q?: string; suburb?: string; scene?: string };

// 筛选条件全部走 URL query，服务端渲染，不需要任何客户端 JS——
// 目标用户九成用手机，首屏更快，也没有水合开销。
function href(cur: Query, key: keyof Query, value: string) {
  const next: Query = { ...cur };
  if (next[key] === value) delete next[key];
  else next[key] = value;
  const qs = new URLSearchParams(
    Object.entries(next).filter(([, v]) => v) as [string, string][],
  ).toString();
  return qs ? `/?${qs}` : "/";
}

function Card({ r }: { r: Restaurant }) {
  const c = card(r);
  const ws = warnings(r);
  // ≥2 人提到的才算共识，放最显眼的位置；只有 1 人说的留到详情页
  const strong = ws.find((w) => w.mentions >= 2);
  const top = dishes(r).slice(0, 3);
  const bits = [priceText(r), r.suburb && suburbLabel(r.suburb), r.cuisine].filter(Boolean);

  return (
    <Link href={`/store/${r.id}`} className="item">
      <h2>{r.name}</h2>
      <p className="meta">
        {bits.map((b, i) => (
          <span key={i}>
            {i > 0 && <span className="sep">·</span>}
            {b}
          </span>
        ))}
      </p>

      {strong ? (
        <p className="warn-row">
          <b>慎选：{strong.subject}</b>
          {strong.reason && <span className="why">　{strong.reason}</span>}
          <span className="cite">
            {strong.mentions}/{c?.review_count ?? "?"}
          </span>
        </p>
      ) : ws.length ? (
        <p className="warn-none">
          有 {ws.length} 条只有 1 个人提到的情况，点进来看
        </p>
      ) : (
        <p className="warn-none">
          这几条评论里没人提到问题（只看了 {c?.review_count ?? "几"} 条）
        </p>
      )}

      {top.length > 0 && (
        <p className="pick-row">
          <span className="k">必点</span>
          {top.map((d, i) => (
            <span key={d.name_raw}>
              {i > 0 && "、"}
              {d.name_raw}
              {d.mentions >= 2 && <span className="cite">{d.mentions} 人夸</span>}
            </span>
          ))}
        </p>
      )}
    </Link>
  );
}

// searchParams 是运行时数据，不能在预渲染时读。按文档的做法把它整体交给
// Suspense 里的异步子组件：外壳先到手机上，列表随后流式补齐。
async function Results({ searchParams }: { searchParams: Promise<Query> }) {
  const sp = await searchParams;
  const all = await getRestaurants();
  const suburbs = [...new Set(all.map((r) => r.suburb).filter(Boolean))].sort() as string[];

  const shown = all.filter((r) => {
    if (sp.suburb && r.suburb !== sp.suburb) return false;
    if (sp.scene && !(card(r)?.scene_tags ?? []).includes(sp.scene)) return false;
    return matches(r, sp.q ?? "");
  });

  return (
    <>
      <form className="search" action="/">
        {sp.suburb && <input type="hidden" name="suburb" value={sp.suburb} />}
        {sp.scene && <input type="hidden" name="scene" value={sp.scene} />}
        <input
          name="q"
          defaultValue={sp.q ?? ""}
          placeholder="店名、菜名都能搜"
          aria-label="搜索"
        />
        <button type="submit">搜索</button>
      </form>

      <div className="chips">
        <span className="label">场景</span>
        {Object.entries(SCENES).map(([k, label]) => (
          <Link key={k} href={href(sp, "scene", k)} className={`chip${sp.scene === k ? " on" : ""}`}>
            {label}
          </Link>
        ))}
      </div>

      <div className="chips">
        <span className="label">区域</span>
        {suburbs.map((s) => (
          <Link key={s} href={href(sp, "suburb", s)} className={`chip${sp.suburb === s ? " on" : ""}`}>
            {suburbLabel(s)}
          </Link>
        ))}
      </div>

      <p className="count">
        {shown.length} 家店
        {shown.length !== all.length && `（共 ${all.length} 家）`}
      </p>

      <div className="list">
        {shown.length ? (
          shown.map((r) => <Card key={r.id} r={r} />)
        ) : (
          <p className="none">没有符合条件的店。换个条件试试。</p>
        )}
      </div>
    </>
  );
}

export default function Page(props: { searchParams: Promise<Query> }) {
  return (
    <main className="wrap">
      <header className="top">
        <div className="brand">SydBite</div>
        <p className="tagline">不告诉你哪家店最好，告诉你这家店适不适合你这顿饭</p>
      </header>

      <Suspense fallback={<p className="count">正在载入…</p>}>
        <Results searchParams={props.searchParams} />
      </Suspense>

      <p className="foot">
        每家店取 Google 地图默认排序的前几条公开评论，未经人工挑选，由大语言模型自动提炼。
        每条结论都标着几条评论提到，并附可回溯的原句。
        <br />
        这是一个个人练习项目，不接受商家合作，也因此可以直说缺点。
      </p>
    </main>
  );
}
