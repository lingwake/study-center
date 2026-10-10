#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习中心 —— 本地服务（静态托管 + B站接口转发）
================================================
作用：
  1) 把 bilibili-player 目录作为网页提供出去，平板用浏览器访问即可打开应用
  2) 提供一个 /api/pages 接口，把 B站的分P数据转发给网页（解决浏览器跨域限制）
     —— 平板点"刷新集数"时，就是调这个接口实时去B站拉最新列表

启动：
    python3 server.py
  启动后终端会打印两个地址：
    - 本机访问：  http://127.0.0.1:8000
    - 平板访问：  http://电脑的局域网IP:8000   （需平板与电脑在同一 WiFi）

可选参数：
    python3 server.py --port 8080      指定端口
"""

import os
import re
import sys
import json
import time
import socket
import argparse
import threading
import urllib.request
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

API_VIEW = "https://api.bilibili.com/x/web-interface/view?bvid={}"

BILI_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 简单的内存缓存：{bvid: (时间戳, 数据)}，5 分钟内不重复打B站
_cache = {}
_CACHE_TTL = 300
_lock = threading.Lock()


def fetch_bili(bvid: str) -> dict:
    """向B站请求分P数据"""
    url = API_VIEW.format(urllib.parse.quote(bvid))
    req = urllib.request.Request(url, headers=BILI_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    if raw.get("code") != 0:
        raise RuntimeError(f"B站接口错误 code={raw.get('code')} {raw.get('message')}")

    d = raw["data"]
    pages = [{
        "page": p["page"],
        "title": p["part"],
        "duration": p["duration"],
    } for p in d.get("pages", [])]

    return {
        "bvid": d["bvid"],
        "title": d["title"],
        "owner": d.get("owner", {}).get("name", ""),
        "ownerFace": d.get("owner", {}).get("face", ""),
        "pic": d.get("pic", ""),
        "desc": d.get("desc", ""),
        "duration": d.get("duration", 0),
        "pubdate": d.get("pubdate", 0),
        "tname": d.get("tname", ""),
        "total": len(pages),
        "pages": pages,
        "fetchedAt": int(time.time() * 1000),
    }


def get_bili_cached(bvid: str) -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get(bvid)
        if hit and now - hit[0] < _CACHE_TTL:
            data = dict(hit[1])
            data["cached"] = True
            return data
    data = fetch_bili(bvid)
    with _lock:
        _cache[bvid] = (now, data)
    out = dict(data)
    out["cached"] = False
    return out


# ---------------- 工具 ----------------
def extract_bvid(text: str) -> str:
    """从 BV号 / 分享链接 / 短链文本里提取 BV 号"""
    if not text:
        return ""
    s = str(text).strip()
    m = re.search(r"BV[0-9A-Za-z]{10}", s)
    if m:
        return m.group(0)
    m = re.search(r"av(\d+)", s, re.I)
    if m:
        return "av" + m.group(1)
    return ""


# ---------------- 配置读写（支持云端持久化目录） ----------------
# 优先用环境变量 DATA_DIR 指定的目录(云端挂载持久盘时使用)
# 未设置时用脚本所在目录(本地电脑使用)
_DATA_DIR = os.environ.get("DATA_DIR", "").strip()
if _DATA_DIR:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        _DATA_DIR = HERE
else:
    _DATA_DIR = HERE

CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")

# 首次启动时，若数据目录没有配置，则从项目自带的 config.json 复制一份作为初始值
_SEED_CONFIG = os.path.join(HERE, "config.json")

DEFAULT_CONFIG = {
    "appName": "学习中心",
    "subtitle": "点击卡片开始学习 · 纯净播放模式",
    "grades": ["5-6年级", "7-9年级", "高一-高三"],
    "items": [],
}


def load_config() -> dict:
    # 初次运行：从种子配置初始化
    if not os.path.exists(CONFIG_PATH) and os.path.exists(_SEED_CONFIG) and _DATA_DIR != HERE:
        try:
            with open(_SEED_CONFIG, encoding="utf-8") as f:
                seed = json.load(f)
            save_config(seed)
        except Exception:
            pass

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                cfg.setdefault("items", [])
                cfg.setdefault("grades", ["5-6年级", "7-9年级", "高一-高三"])
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG, items=[])


def save_config(cfg: dict) -> None:
    # 原子写入，避免写一半损坏
    try:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        print(f"[警告] 保存配置失败: {e}")
        raise


class Handler(SimpleHTTPRequestHandler):
    """静态文件 + /api/pages 转发"""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    # 静音本来的逐条日志（保留错误）
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # —— 接口：/api/pages?bvid=BVxxxx （刷新集数）——
        if parsed.path == "/api/pages":
            qs = urllib.parse.parse_qs(parsed.query)
            bvid = (qs.get("bvid", [""])[0] or "").strip()
            if not bvid:
                self._send_json({"ok": False, "error": "缺少 bvid 参数"}, 400)
                return
            if not (bvid.startswith("BV") or bvid.startswith("av")):
                self._send_json({"ok": False, "error": "bvid 格式不正确"}, 400)
                return
            try:
                data = get_bili_cached(bvid)
                self._send_json({"ok": True, "data": data})
                print(f"[刷新] {bvid} → {data['total']} 集"
                      f"{' (缓存)' if data.get('cached') else ''}")
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 502)
                print(f"[失败] {bvid}: {e}")
            return

        # —— 接口：/api/config （读取当前配置）——
        if parsed.path == "/api/config":
            self._send_json({"ok": True, "data": load_config()})
            return

        # —— 接口：/api/export （下载 config.json，用于存回 GitHub）——
        if parsed.path == "/api/export":
            cfg = load_config()
            body = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=config.json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            print("[导出] config.json")
            return

        # —— 接口：/api/preview?bvid=xxx （导入前预览视频信息）——
        if parsed.path == "/api/preview":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0] or "").strip()
            bvid = extract_bvid(q)
            if not bvid:
                self._send_json({"ok": False, "error": "没识别到 BV 号，请检查后重试"}, 400)
                return
            try:
                data = get_bili_cached(bvid)
                self._send_json({"ok": True, "data": data})
                print(f"[预览] {bvid} → {data['title']} ({data['total']} 集)")
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 502)
                print(f"[预览失败] {bvid}: {e}")
            return

        # —— 其余走静态文件 ——
        # 根路径默认返回 index.html
        if parsed.path in ("/", ""):
            self.path = "/index.html"
        super().do_GET()

    # —— POST：导入 / 删除 / 保存配置 ——
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._read_body_json()

        # 导入一个视频到 config.json
        if parsed.path == "/api/import":
            raw_input = (body.get("q") or "").strip()
            title = (body.get("title") or "").strip()
            badge = (body.get("badge") or "").strip()
            desc = (body.get("desc") or "").strip()

            bvid = extract_bvid(raw_input)
            if not bvid:
                self._send_json({"ok": False, "error": "没识别到 BV 号"}, 400)
                return
            try:
                info = get_bili_cached(bvid)
            except Exception as e:
                self._send_json({"ok": False, "error": f"读取视频信息失败：{e}"}, 502)
                return

            cfg = load_config()
            items = cfg.setdefault("items", [])
            if any(extract_bvid(i.get("bvid", "")) == bvid for i in items):
                self._send_json({"ok": False, "error": "这个视频已经在列表里了"}, 409)
                return

            items.append({
                "title": title or info["title"],
                "desc": desc or (f"UP主：{info['owner']}" if info.get("owner") else ""),
                "badge": badge or (info.get("tname") or "视频"),
                "bvid": bvid,
                "page": 1,
                "grade": (body.get("grade") or "").strip(),
            })
            save_config(cfg)
            self._send_json({"ok": True, "data": cfg, "added": {
                "bvid": bvid, "title": info["title"], "total": info["total"],
            }})
            print(f"[导入] {bvid} → {info['title']} ({info['total']} 集)")
            return

        # 编辑一个已导入视频（改名称 / 改分类 / 改备注）
        if parsed.path == "/api/edit":
            bvid = extract_bvid(body.get("bvid", "") or "")
            if not bvid:
                self._send_json({"ok": False, "error": "缺少 bvid"}, 400)
                return
            cfg = load_config()
            items = cfg.get("items", [])
            hit = None
            for i in items:
                if extract_bvid(i.get("bvid", "")) == bvid:
                    hit = i
                    break
            if hit is None:
                self._send_json({"ok": False, "error": "没找到这个视频"}, 404)
                return

            # 只更新显式传入的字段
            if isinstance(body.get("title"), str):
                t = body["title"].strip()
                if t:
                    hit["title"] = t
            if isinstance(body.get("grade"), str):
                hit["grade"] = body["grade"].strip()
            if isinstance(body.get("desc"), str):
                hit["desc"] = body["desc"].strip()
            if isinstance(body.get("badge"), str):
                hit["badge"] = body["badge"].strip()

            save_config(cfg)
            self._send_json({"ok": True, "data": cfg})
            print(f"[编辑] {bvid} → title={hit.get('title')} grade={hit.get('grade','')}")
            return

        # 从 config.json 删除一个视频
        if parsed.path == "/api/delete":
            if not bvid:
                self._send_json({"ok": False, "error": "缺少 bvid"}, 400)
                return
            cfg = load_config()
            before = len(cfg.get("items", []))
            cfg["items"] = [i for i in cfg.get("items", [])
                            if extract_bvid(i.get("bvid", "")) != bvid]
            if len(cfg["items"]) == before:
                self._send_json({"ok": False, "error": "没找到这个视频"}, 404)
                return
            save_config(cfg)
            self._send_json({"ok": True, "data": cfg})
            print(f"[删除] {bvid}")
            return

        # 保存整个配置（标题等）
        if parsed.path == "/api/save-config":
            cfg = load_config()
            for k in ("appName", "subtitle"):
                if isinstance(body.get(k), str):
                    cfg[k] = body[k]
            save_config(cfg)
            self._send_json({"ok": True, "data": cfg})
            print("[配置] 已保存")
            return

        self._send_json({"ok": False, "error": "未知接口"}, 404)

    # 预检请求
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


def lan_ip() -> str:
    """取本机局域网 IP"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    # 云平台通过环境变量 PORT 指定端口，其次才是命令行参数
    env_port = os.environ.get("PORT", "").strip()
    default_port = int(env_port) if env_port.isdigit() else 8000
    ap.add_argument("--port", type=int, default=default_port)
    args = ap.parse_args()

    port = args.port
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    ip = lan_ip()

    print("=" * 56)
    print("  学习中心  服务已启动")
    print("=" * 56)
    print(f"  本机打开：   http://127.0.0.1:{port}")
    print(f"  局域网/平板：http://{ip}:{port}")
    print()
    print(f"  配置存储目录：{_DATA_DIR}")
    print(f"  配置文件夹：  {CONFIG_PATH}")
    print()
    print("  · 本地使用：平板需与本电脑连接同一个 WiFi")
    print("  · 平板页面里点【刷新集数】即可拉取B站最新集数")
    print("  · 按 Ctrl+C 停止服务")
    print("=" * 56)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
