#!/usr/bin/env python3
"""验证 Supabase 连接是否可用，并列出当前已暴露的表。

用法：python3 pipeline/check_db.py

只用标准库。两把 key 分别测一次：
  anon / publishable  —— 前端会用的公开 key
  service_role/secret —— 离线管线用的万能 key，绕过 RLS
"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from extract import load_env  # noqa: E402  复用同一份 .env.local 读取逻辑


def get(base, key, path):
    req = urllib.request.Request(base.rstrip("/") + path, headers={
        "apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return None, str(e.reason).encode()


def probe(base, key, label):
    """返回 API 说明书（若该 key 有权限读），并打印判定结果。

    注意 /rest/v1/ 这个端点现在只接受 secret key，anon 拿到 401 是正常的，
    不代表 key 无效。所以 anon 改用「查一张不存在的表」来验证：
    key 有效会返回「找不到该表」，key 无效才会返回「密钥错误」。
    """
    status, body = get(base, key, "/rest/v1/")
    text = body.decode("utf-8", "replace")
    if status == 200:
        print(f"  ✓ {label:<22} 连接正常")
        return json.loads(text) if text else {}
    if status == 401 and "secret" in text.lower():
        s2, b2 = get(base, key, "/rest/v1/__probe_not_exist__?select=*")
        t2 = b2.decode("utf-8", "replace").lower()
        if s2 in (404, 400) and ("not exist" in t2 or "could not find" in t2 or "pgrst205" in t2):
            print(f"  ✓ {label:<22} 连接正常（该 key 无权读 API 说明书端点，属正常）")
        elif s2 in (401, 403):
            print(f"  ✗ {label:<22} 密钥无效：{b2.decode('utf-8','replace')[:140]}")
        else:
            print(f"  ? {label:<22} HTTP {s2}  {b2.decode('utf-8','replace')[:140]}")
        return None
    print(f"  ✗ {label:<22} HTTP {status}  {text[:160]}")
    return None


def main():
    env = load_env()
    base = env.get("NEXT_PUBLIC_SUPABASE_URL")
    anon = env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    svc = env.get("SUPABASE_SERVICE_ROLE_KEY")
    missing = [k for k, v in (("NEXT_PUBLIC_SUPABASE_URL", base),
                              ("NEXT_PUBLIC_SUPABASE_ANON_KEY", anon),
                              ("SUPABASE_SERVICE_ROLE_KEY", svc)) if not v]
    if missing:
        sys.exit(".env.local 里这些还是空的：" + ", ".join(missing))

    print(f"项目：{base}\n")
    spec = probe(base, anon, "anon / publishable")
    spec2 = probe(base, svc, "service_role / secret")

    tables = sorted((spec or spec2 or {}).get("definitions", {}).keys())
    print(f"\n已暴露的表：{'、'.join(tables) if tables else '（空——还没建表，正常）'}")


if __name__ == "__main__":
    main()
