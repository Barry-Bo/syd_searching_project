#!/usr/bin/env python3
"""对 samples/ 下所有店批量跑提炼 + 校验，输出汇总表。

用法：
    python3 pipeline/run_all.py                      # 默认 v5
    python3 pipeline/run_all.py --prompt v5 --model qwen3.7-flash

中转站经常返回 502，脚本内置退避重试；单店失败不会中断整批。
"""
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402

ROOT = extract.ROOT


def call_with_retry(env, prompt, tries=5):
    body = json.dumps({
        "model": env["LLM_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    last = None
    for i in range(tries):
        req = urllib.request.Request(
            env["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + env["LLM_API_KEY"]})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read()), None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503, 504):
                return None, last + " " + e.read().decode("utf-8", "replace")[:200]
        except Exception as e:  # 网络抖动
            last = str(e)
        time.sleep(6 * (i + 1))
    return None, f"重试 {tries} 次仍失败：{last}"


def main():
    args = sys.argv[1:]
    version, model = "v5", None
    if "--prompt" in args:
        version = args[args.index("--prompt") + 1]
    if "--model" in args:
        model = args[args.index("--model") + 1]

    env = extract.load_env()
    if model:
        env["LLM_MODEL"] = model
    template = extract.load_prompt(version)

    files = sorted(f for f in glob.glob(os.path.join(ROOT, "pipeline", "samples", "*.json"))
                   if not os.path.basename(f).startswith("_"))
    if not files:
        sys.exit("samples/ 下没有店铺文件。先用 paste2json.py 生成。")

    print(f"prompt {version} · {env['LLM_MODEL']} · {len(files)} 家店\n")
    rows, tok = [], 0
    for path in files:
        data = json.load(open(path, encoding="utf-8"))
        name = data["name"]
        stem = os.path.splitext(os.path.basename(path))[0]
        print(f"  跑 {name} …", end="", flush=True)

        resp, err = call_with_retry(env, extract.build_prompt(
            template, name, data["reviews"]))
        if err:
            print(f" 失败（{err}）")
            rows.append((name, "调用失败", "-", 0))
            continue

        card, perr = extract.parse_card(resp["choices"][0]["message"]["content"])
        u = resp.get("usage", {})
        tok += u.get("total_tokens", 0)
        if card is None:
            print(" 输出非合法 JSON")
            rows.append((name, "JSON 解析失败", "-", u.get("total_tokens", 0)))
            continue

        out = os.path.join(ROOT, "pipeline", "out",
                           f"{stem}__{version}__{env['LLM_MODEL']}.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(card, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        r = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", "verify.py"),
                            path, out], capture_output=True, text=True)
        rate = next((l.split("：")[1] for l in r.stdout.splitlines()
                     if l.startswith("通过率")), "?")
        nfail = next((l for l in r.stdout.splitlines() if l.startswith("共 ")), "")
        print(f" {rate}")
        rows.append((name, rate, len(card.get("慎选") or []), u.get("total_tokens", 0)))
        if r.returncode:
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(f"      {l.strip()}")

    print(f"\n{'店名':<34}{'通过率':<10}{'慎选':<6}{'token'}")
    print("-" * 60)
    for n, rate, nsel, t in rows:
        print(f"{n[:32]:<34}{str(rate):<10}{str(nsel):<6}{t}")
    print("-" * 60)
    print(f"合计 {len(rows)} 家店，{tok:,} token，约 ¥{tok/7300*0.0046:.3f}（按 qwen 实测均价估）")


if __name__ == "__main__":
    main()
