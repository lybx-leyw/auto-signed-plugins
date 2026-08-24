#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
worker.py — 学在浙大自动签到 · 长驻监控进程

Evergreen module.process 入口（scope=long, autoStart=true, autoRestart=true,
protocol=http, runtime=python）。由 ModuleLoader 在应用启动时拉起：
  - stdout 第一行必须输出 `PORT:<port>`，随后提供 GET /health（返回 200）
  - 后台线程持续轮询点名并自动应答（仅 stdlib，零第三方依赖）
  - 状态写入同目录 state.json，供 data/autosign.py 与模块页展示
  - 日志走 stderr；stdout 只输出 PORT 行

控制方式：
  - 暂停/恢复：修改设置项 AUTOSIGN_ENABLED（模块页一键切换，每轮重读配置）
  - 立即签到：GET /checkin-now 触发一轮即时检查（也供平台 bridge 后续调用）
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import autosign_core as core

# ═══════════ 共享状态 ═══════════

_state = core.load_state()
_state.setdefault("history", [])
_state.setdefault("pollCount", 0)
_state["pid"] = os.getpid()
_state["startedAt"] = _state.get("startedAt") or core._now()
_state["worker"] = True
_state_lock = threading.Lock()
_stop = threading.Event()
_session = {"obj": None}          # 登录会话（失效后置 None 强制重登）
_manual_check = threading.Event()  # /checkin-now 触发一轮即时检查


def _snapshot():
    with _state_lock:
        return dict(_state)


def _set_state(**kw):
    with _state_lock:
        _state.update(kw)


# ═══════════ HTTP 服务（PORT:/health 协议） ═══════════

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._json(200, {"status": "ok", "pid": _state.get("pid")})
        elif path == "/status":
            self._json(200, _snapshot())
        elif path == "/checkin-now":
            _manual_check.set()
            self._json(200, {"ok": True, "message": "已触发一轮即时检查"})
        else:
            self._json(404, {"error": "not found"})


# ═══════════ 监控循环 ═══════════

def monitor_loop():
    while not _stop.is_set():
        cfg = core.load_config()
        _set_state(
            enabled=cfg["enabled"],
            location=cfg["location"],
            interval=cfg["interval"],
            updatedAt=core._now(),
        )

        if not cfg["username"] or not cfg["password"]:
            _set_state(
                running=False,
                error="请先在设置面板配置 ZJU_USERNAME / ZJU_PASSWORD（统一认证账号密码）",
            )
            core.save_state(_snapshot())
            _stop.wait(10)
            continue

        try:
            if _session["obj"] is None:
                _session["obj"] = core.ZJUCoursesSession(cfg["username"], cfg["password"])
                _session["obj"].login()
            sess = _session["obj"]

            if _manual_check.is_set():
                _manual_check.clear()
                snap = core.run_cycle(sess, cfg, _snapshot())
                _set_state(**snap)

            if cfg["enabled"]:
                snap = core.run_cycle(sess, cfg, _snapshot())
                _set_state(**snap)
                _set_state(running=True)
            else:
                _set_state(running=False, note="自动签到已暂停（AUTOSIGN_ENABLED=false）")
            core.save_state(_snapshot())
        except Exception as e:
            _session["obj"] = None  # 强制下次重登
            _set_state(running=False, error=str(e))
            core.save_state(_snapshot())
            core._log("监控循环异常: %s\n%s" % (e, traceback.format_exc()))
            _stop.wait(5)

        _stop.wait(max(2, min(60, cfg["interval"])))


# ═══════════ 入口 ═══════════

def main():
    ap = argparse.ArgumentParser(description="学在浙大自动签到 worker")
    ap.add_argument("--project-root", default="", help="平台注入的项目根目录")
    ap.add_argument("--port", type=int, default=0, help="HTTP 端口（0=自动分配）")
    ap.add_argument("--type", default="", help="兼容数据源参数，忽略")
    ap.add_argument("--greenix-config", default="", help="兼容数据源参数，忽略")
    args, _ = ap.parse_known_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port or 0), Handler)
    port = server.server_address[1]
    print("PORT:%d" % port, flush=True)  # ← ModuleLoader 端口发现契约
    core._log("worker 已启动，监听 127.0.0.1:%d" % port)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()

    try:
        while not _stop.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _stop.set()
        server.shutdown()
        core.save_state(_snapshot())
    return 0


if __name__ == "__main__":
    sys.exit(main())
