#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站分P数据抓取工具
-------------------
用途：抓取指定 B站视频的全部分P（集数）标题和时长，生成本地缓存文件 pages.json，
     供学习中心网页应用读取，实现"选集播放"功能。

用法：
    python3 fetch_pages.py BV1mkKr6jENy BV1xxxxxxxxx ...
    python3 fetch_pages.py            # 不带参数则读取 config.json 里的所有 bvid

说明：浏览器因跨域限制无法直接调 B站接口，所以需要在电脑上用此脚本生成数据，
     再把生成的 pages.json 和 index.html 一起拷到平板即可。
"""

import sys
import os
import json
import time
import urllib.request
import urllib.parse

API = "https://api.bilibili.com/x/web-interface/view?bvid={}"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pages.json")
CONFIG = os.path.join(HERE, "config.json")


def fetch(bvid: str) -> dict:
    """抓取单个视频的基本信息 + 分P列表"""
    url = API.format(urllib.parse.quote(bvid))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("code") != 0:
        raise RuntimeError(f"接口返回错误 code={data.get('code')} message={data.get('message')}")

    d = data["data"]
    pages = []
    for p in d.get("pages", []):
        pages.append({
            "page": p["page"],
            "title": p["part"],
            "duration": p["duration"],
        })

    return {
        "bvid": d["bvid"],
        "title": d["title"],
        "owner": d.get("owner", {}).get("name", ""),
        "total": len(pages),
        "pages": pages,
    }


def bvids_from_config() -> list:
    """从 config.json 读取所有需要抓取的 bvid"""
    if not os.path.exists(CONFIG):
        return []
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        out = []
        for it in cfg.get("items", []):
            v = (it.get("bvid") or "").strip()
            if v:
                out.append(v)
        return out
    except Exception as e:
        print(f"[警告] 读取 config.json 失败: {e}")
        return []


def main():
    args = [a.strip() for a in sys.argv[1:] if a.strip()]
    if args:
        targets = args
    else:
        targets = bvids_from_config()
        if targets:
            print(f"[信息] 未指定 BV 号，从 config.json 读取到 {len(targets)} 个")
        else:
            print("用法: python3 fetch_pages.py BV1mkKr6jENy [BV2xxx ...]")
            print("      或不带参数(自动读取 config.json 里的 bvid)")
            sys.exit(1)

    # 读取已有缓存，支持增量更新
    cache = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                old = json.load(f)
                for k, v in old.items():
                    cache[k] = v
        except Exception:
            pass

    ok, fail = 0, 0
    for i, bv in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] 正在抓取 {bv} ...", end=" ", flush=True)
        try:
            info = fetch(bv)
            cache[bv] = info
            ok += 1
            print(f"✓ {info['total']} 集 —— {info['title']}")
        except Exception as e:
            fail += 1
            print(f"✗ 失败: {e}")
        if i < len(targets):
            time.sleep(0.8)  # 温和请求，避免被限流

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n完成：成功 {ok} 个，失败 {fail} 个")
    print(f"数据已写入: {OUT}")
    print("把 index.html、config.json、pages.json 一起拷到平板即可。")


if __name__ == "__main__":
    main()
