#!/usr/bin/env python3
"""把一家店的评论提炼成四维卡片。

用法：
    python3 pipeline/extract.py pipeline/samples/xxx.json
    python3 pipeline/extract.py pipeline/samples/xxx.json --prompt v2

输入 JSON 格式：{"name": "店名", "reviews": ["评论1", "评论2", ...]}
只用标准库，不需要 pip install。
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    """从 .env.local 读配置。不依赖 shell 有没有 source 过。"""
    env = {}
    path = os.path.join(ROOT, ".env.local")
    if not os.path.exists(path):
        sys.exit("找不到 .env.local，先从 .env.example 复制一份并填好 key")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if not env.get(key):
            sys.exit(f".env.local 里 {key} 是空的")
    return env


def load_prompt(version):
    """从 prompts/vN.md 里取出 <PROMPT>...</PROMPT> 之间的正文。

    这样 prompt 文件既能给人读（有设计决策和评测记录），又能给机器用。
    """
    path = os.path.join(ROOT, "pipeline", "prompts", f"{version}.md")
    if not os.path.exists(path):
        sys.exit(f"找不到 {path}")
    text = open(path, encoding="utf-8").read()
    m = re.search(r"<PROMPT>(.*?)</PROMPT>", text, re.S)
    if not m:
        sys.exit(f"{path} 里没找到 <PROMPT>...</PROMPT> 标记")
    return m.group(1).strip()


def build_prompt(template, name, reviews):
    numbered = "\n".join(f"[{i}] {r}" for i, r in enumerate(reviews, 1))
    return (template
            .replace("{{NAME}}", name)
            .replace("{{COUNT}}", str(len(reviews)))
            .replace("{{REVIEWS}}", numbered))


def call_llm(env, prompt):
    body = json.dumps({
        "model": env["LLM_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        # 抽取任务要稳定复现，不要随机性
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        env["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + env["LLM_API_KEY"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}：{e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"网络错误：{e.reason}")


def parse_card(content):
    """模型可能违反指令套一层 ```json 代码块，这里兜住。"""
    content = content.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if m:
        content = m.group(1).strip()
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        return None, f"{e}\n--- 原始输出 ---\n{content}"


def main():
    args = [a for a in sys.argv[1:]]
    version = "v1"
    override_model = None
    if "--prompt" in args:
        i = args.index("--prompt")
        version = args[i + 1]
        del args[i:i + 2]
    if "--model" in args:
        i = args.index("--model")
        override_model = args[i + 1]
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)

    data = json.load(open(args[0], encoding="utf-8"))
    name, reviews = data["name"], data["reviews"]
    env = load_env()
    if override_model:
        env["LLM_MODEL"] = override_model

    prompt = build_prompt(load_prompt(version), name, reviews)
    resp = call_llm(env, prompt)

    if "choices" not in resp:
        sys.exit("接口返回异常：\n" + json.dumps(resp, ensure_ascii=False, indent=2))

    card, err = parse_card(resp["choices"][0]["message"]["content"])

    print(f"=== {name} · prompt {version} · {env['LLM_MODEL']} · {len(reviews)} 条评论 ===\n")
    if card is None:
        print("!! 输出不是合法 JSON，这本身就是一条评测结论（格式遵循失败）")
        print(err)
    else:
        print(json.dumps(card, ensure_ascii=False, indent=2))

    if card is not None:
        os.makedirs(os.path.join(ROOT, "pipeline", "out"), exist_ok=True)
        stem = os.path.splitext(os.path.basename(args[0]))[0]
        out = os.path.join(ROOT, "pipeline", "out",
                           f"{stem}__{version}__{env['LLM_MODEL']}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
        print(f"\n已存到 {os.path.relpath(out, ROOT)}")

    u = resp.get("usage", {})
    detail = u.get("completion_tokens_details", {}) or {}
    print(f"\n--- 用量 ---")
    print(f"输入 {u.get('prompt_tokens')} / 输出 {u.get('completion_tokens')} "
          f"(其中思考 {detail.get('reasoning_tokens', 0)}) / 合计 {u.get('total_tokens')}")
    print("去网站「使用日志」查这次实际扣了多少钱，记进 prompts/%s.md" % version)


if __name__ == "__main__":
    main()
