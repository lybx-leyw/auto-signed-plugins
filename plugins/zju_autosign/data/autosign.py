#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autosign.py — 学在浙大自动签到 · 数据源适配壳（Evergreen data-source）

被平台按需调用：
    python autosign.py --type zju_autosign --project-root <root> --greenix-config <cfg>

行为：
  1. 若 module/state.json 新鲜（<90s）→ 直接回显 worker 的实时状态（零成本）
  2. 否则自行执行一轮「登录 → 轮询 → 应答点名 → 推送钉钉」的即时检查，
     保证即使 worker 未运行，模块页/「立即签到」仍可用

平台契约：
  - stdout 只输出纯 JSON；日志走 stderr
  - 失败时 stdout 输出 {"error": "..."} 且 exit code 非 0
  - 凭证走 _get_config 三级降级，绝不硬编码
"""
import argparse
import json
import os
import sys
import time

# 允许从插件根目录导入 module/autosign_core.py（data/ 与 module/ 为兄弟目录）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "module"))

import autosign_core as core  # noqa: E402

STATE_FRESH_SECONDS = 90


def _read_fresh_state():
    """读取 worker 写入的状态文件；新鲜则返回内容字符串，否则 None。"""
    try:
        if os.path.exists(core.STATE_PATH):
            age = time.time() - os.path.getmtime(core.STATE_PATH)
            if age < STATE_FRESH_SECONDS:
                with open(core.STATE_PATH, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if raw:
                    json.loads(raw)  # 校验是合法 JSON
                    return raw
    except Exception as e:
        core._log("读取状态文件失败: %s" % e)
    return None


def main():
    ap = argparse.ArgumentParser(description="学在浙大自动签到数据源")
    ap.add_argument("--type", default="zju_autosign")
    ap.add_argument("--project-root", default="")
    ap.add_argument("--greenix-config", default="")
    args, _ = ap.parse_known_args()

    # 1) worker 正在跑 → 回显其最新状态
    fresh = _read_fresh_state()
    if fresh is not None:
        print(fresh)
        return 0

    # 2) worker 未运行/状态过期 → 自己执行一轮即时检查
    cfg = core.load_config()
    if not cfg["username"] or not cfg["password"]:
        print(json.dumps({
            "error": "请先在设置面板配置 ZJU_USERNAME / ZJU_PASSWORD（统一认证账号密码）"
        }, ensure_ascii=False))
        return 1

    session = core.ZJUCoursesSession(cfg["username"], cfg["password"])
    try:
        session.login()
        state = core.load_state()
        state["history"] = state.get("history", [])
        state["pollCount"] = state.get("pollCount", 0)
        state = core.run_cycle(session, cfg, state)
        state["running"] = False
        state["source"] = "one-shot"
        core.save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
