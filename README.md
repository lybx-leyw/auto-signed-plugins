# Evergreen 插件 · 学在浙大自动签到（zju_autosign）

自动监控并应答**学在浙大**（courses.zju.edu.cn）的课堂点名：雷达点名（GPS 坐标提交）与
数字点名（数字码穷举），签到结果实时推送钉钉。逻辑移植自
[ZJU-live-better](https://github.com/cubicYYY/ZJU-live-better) 的 `courses.zju/autosign.js`，
并严格遵循 Evergreen 插件协议（凭证三级降级、stdout 纯 JSON、零硬编码）。

> **安全边界**：本插件不收集、不上传任何数据。凭证只保存在本机 Evergreen 设置中，
> 由脚本按平台契约三级降级读取。签到行为与手动在手机上签到相同（提交 GPS 坐标 / 数字码），
> 请自行确认符合学校与课程要求。

---

## 一、插件结构

```
plugins/zju_autosign/
├── module/
│   ├── manifest.json      # module 声明（HTML 仪表盘 + 长驻 worker 进程）
│   ├── index.html         # 仪表盘页（platform bridge：状态/开关/立即签到/地点切换）
│   ├── worker.py          # 长驻监控进程（module.process，scope=long，随 Evergreen 启动）
│   └── autosign_core.py   # 共享核心：CAS 登录 / 雷达+数字点名 / 钉钉 / 状态文件
├── data/
│   ├── manifest.json      # data-source 声明（zju_autosign，ttl=0s）
│   └── autosign.py        # 状态适配壳（优先回显 worker 状态，兜底单次即时检查）
└── config/
    └── config.json        # 新增设置项声明（AUTOSIGN_*）
```

**双通道设计**：

| 通道 | 机制 | 何时生效 |
|---|---|---|
| worker 常驻监控 | `module.process`（scope=long, autoStart, autoRestart）随 Evergreen 启动，后台线程按轮询间隔检查并应答 | Evergreen 运行期间（无需打开模块页） |
| 页面/数据源兜底 | `data-source`（ttl=0s）+ 模块页 `platform.data.subscribe` 5s 轮询；状态过期时数据源自行执行一轮即时检查 | 打开模块页时；「立即签到」按钮 |

两通道共用 `module/state.json`，互不冲突（同一点名已被应答后状态变为
`on_call_fine`，另一通道会自动跳过）。

---

## 二、安装

1. 将整个 `plugins/zju_autosign` 目录复制到 Evergreen 的插件目录 `plugins/` 下
   （或用市场安装 `.plugin` 包——见「打包」）。
2. **重启 Evergreen**。启动时 `ModuleLoader` 会自动拉起 worker
   （要求 Python 可用；平台内嵌 Python 即可，本插件零第三方依赖）。
3. 打开侧边栏「校园 → 学在浙大自动签到」。

> 平台要求：Evergreen v2.0（市场为本地扫描，manifest 带 `schemaVersion: "2.0"`）。

### 打包（可选）

```powershell
# 以插件 id 为根目录打 zip，改名为 zju_autosign.plugin 即可
Compress-Archive -Path plugins/zju_autosign -DestinationPath zju_autosign.plugin
```

---

## 三、配置（设置面板）

**复用平台内置 key（无需新增）**：

| key | 说明 |
|---|---|
| `ZJU_USERNAME` | 学号（统一认证账号），**必填** |
| `ZJU_PASSWORD` | 统一认证密码（secure），**必填** |
| `DINGTALK_WEBHOOK` | 钉钉机器人 Webhook（可选，填写后签到结果自动推送） |
| `DINGTALK_SECRET` | 钉钉加签密钥（可选） |

**插件新增设置项（config/config.json 已声明）**：

| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `AUTOSIGN_ENABLED` | bool | `"true"` | 总开关；关闭后 worker 保持运行但不应答 |
| `AUTOSIGN_RADAR_LOCATION` | option | `"ZJGD1"` | 雷达签到地点（12 个校区点位），失败自动遍历全部点位 → 三点定位 |
| `AUTOSIGN_POLL_INTERVAL` | option | `"4"` | 轮询间隔（2/4/8/15 秒） |

---

## 四、工作流程

```
Evergreen 启动 → ModuleLoader 拉起 worker.py
   ├─ stdout 输出 PORT:<port> → GET /health 通过 → 标记就绪
   └─ 后台监控线程：
       读配置（三级降级）→ 登录 CAS → 循环：
         GET /api/radar/rollcalls
         ├─ 雷达点名 → 配置地点 → 12 个已知点位 → 球面三点定位
         ├─ 数字点名 → 读现成码 → 0000-9999 并发穷举
         └─ 结果写入 state.json + 推送钉钉
模块页（index.html）：
   platform.data.subscribe('zju_autosign') → 5s 拉取实时状态
   「立即签到」→ platform.data.refresh('zju_autosign') → 兜底即时检查
```

**已实现的能力**（对照 autosign.js）：✅ 雷达点名（配置地点优先） ✅ 雷达点位遍历
✅ 三点定位（球面高斯-牛顿最小二乘） ✅ 数字点名（并发穷举 + 现成码读取）
✅ 已应答点名跳过 ✅ 钉钉通知（含加签） ✅ 会话失效自动重登。

---

## 五、上架清单（自检）

- [x] module：`module/manifest.json` 含 `type`/`id`/`name` + `schemaVersion: "2.0"`
- [x] data-source：`data/manifest.json` + 适配壳 `data/autosign.py`（CLI 契约：`--type --project-root --greenix-config`）
- [x] 新增设置项：`config/config.json` 声明（key 带 `AUTOSIGN_` 前缀，全局唯一）
- [x] 凭证：全部走 `_get_config` 三级降级（文件 → ConfigHttpServer → 环境变量），零硬编码
- [x] stdout 契约：worker 只输出 `PORT:` 行；数据源只输出纯 JSON；日志全走 stderr
- [x] 失败收敛：任何异常输出 `{"error": "..."}`，进程不崩、不吐堆栈到 stdout
- [x] 依赖：**纯 Python 标准库**（urllib/http.server/Decimal/ThreadPoolExecutor），无需 `requirements`
- [x] registry：`registry-entry.example.json`（v1 协议参考；v2.0 本地市场无需 registry 条目）

### 已知边界

- 「自动」范围 = **Evergreen 运行期间**。应用退出后无后台任务（平台无跨应用常驻能力）。
- 数字点名穷举 0000-9999 需要若干秒到数分钟（取决于服务端限速），期间页面轮询不受影响。
- 雷达点名成功率依赖已知点位坐标库的时效性；新校区/新楼栋可自行向
  `autosign_core.py` 的 `RADAR_LOCATIONS` 补充坐标。

---

## 六、许可

MIT。代码参考自 [ZJU-live-better](https://github.com/cubicYYY/ZJU-live-better)
（GPL-3.0，本项目为独立重实现，仅借鉴接口协议与坐标数据）。
