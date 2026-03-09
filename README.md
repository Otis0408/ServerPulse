# ServerPulse

**macOS 菜单栏服务器性能监控工具** — 实时监控远程 Linux 服务器的 CPU、内存、硬盘、网络状态。

<p align="center">
  <img src="https://img.shields.io/badge/platform-macOS-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/server-Linux-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/python-3.8+-green?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" />
</p>

---

## 功能特性

- **菜单栏实时网速** — 上行/下行速度紧凑叠放显示
- **详细性能指标** — CPU / 内存 / 硬盘 / 网络 / 系统负载 / 运行时长
- **彩色进度条** — 使用率从绿→黄→橙→红渐变，一目了然
- **流量统计** — 按时间维度统计上行、下行、总流量（今日/1h/6h/24h/7d/30d）
- **连接码配对** — 服务端生成 Base64 连接码，Mac 端粘贴即连，无需配置 SSH 密钥
- **打包为 .app** — 一键构建原生 macOS 应用，放入 Applications 文件夹
- **服务端自启** — 通过 systemd 管理，开机自动运行

## 架构

```
┌─────────────┐         HTTP API         ┌──────────────────┐
│  Mac Client  │ ◄──── (Token Auth) ────► │  Linux Agent     │
│  (Menu Bar)  │     port 9730            │  (Metrics HTTP)  │
└─────────────┘                          └──────────────────┘
      │                                          │
      ├─ rumps (menu bar)                        ├─ /proc/net/dev
      ├─ PyObjC (styled UI)                      ├─ top / free / df
      └─ requests (HTTP client)                  └─ http.server (stdlib)
```

## 快速开始

### 1️⃣ 服务器端（Linux）

```bash
# 上传并安装
scp -r server/ user@your-server:/tmp/serverpulse
ssh user@your-server "cd /tmp/serverpulse && bash install.sh"
```

或手动运行：

```bash
python3 server/monitor_agent.py
```

启动后会输出连接码：

```
  ┌─ Connection Code (paste into Mac app) ─┐
  │ eyJoIjoiMTI3LjAuMC4xIiwicCI6OTczMCwidCI6InRva2VuX2hlcmUifQ
  └─────────────────────────────────────────┘
```

> ⚠️ 请确保服务器防火墙已开放 **9730** 端口（TCP）

### 2️⃣ Mac 客户端

**方式 A：构建 .app（推荐）**

```bash
cd client
bash build.sh
```

构建完成后自动安装到 `/Applications/ServerPulse.app`

**方式 B：直接运行**

```bash
cd client
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python monitor.py
```

### 3️⃣ 连接

启动 Mac 客户端后，粘贴服务器输出的连接码即可。连接信息会保存到本地，下次启动自动连接。

## 技术栈

| 组件 | 技术 |
|------|------|
| Mac 菜单栏 | [rumps](https://github.com/jaredks/rumps) — Ridiculously Uncomplicated macOS Python Statusbar apps |
| Mac UI 样式 | [PyObjC](https://pyobjc.readthedocs.io/) — NSAttributedString, NSImage, NSFont |
| HTTP 通信 | [requests](https://docs.python-requests.org/) (client) / `http.server` stdlib (server) |
| 服务端指标 | `/proc/net/dev`, `top`, `free`, `df` — 零依赖，纯 Python stdlib |
| App 打包 | [py2app](https://py2app.readthedocs.io/) — 构建原生 macOS .app |
| 连接码 | Base64 编码的 JSON (host + port + token) |
| 进程管理 | systemd — 服务端开机自启、崩溃自动重启 |
| 数据持久化 | JSON 文件存储流量数据（~/Library/Application Support/ServerPulse/） |

## 文件结构

```
ServerPulse/
├── server/
│   ├── monitor_agent.py    # 服务端监控代理（HTTP API + 指标采集）
│   └── install.sh          # 一键安装脚本（systemd + 防火墙）
├── client/
│   ├── monitor.py          # Mac 菜单栏主程序
│   ├── traffic_store.py    # 流量数据存储与统计
│   ├── create_icon.py      # App 图标生成器
│   ├── setup_app.py        # py2app 打包配置
│   ├── build.sh            # 一键构建脚本
│   └── requirements.txt    # Python 依赖
├── .gitignore
└── README.md
```

## 安全说明

- 服务端通信使用随机生成的 Token 认证（Bearer Token）
- Token 存储在服务器 `~/.serverpulse_token`（权限 600）
- 建议在生产环境中配合 HTTPS 反向代理使用
- 连接码中包含认证 Token，请勿公开分享

## License

MIT
