# Claude / Codex 连接管理器 · macOS

macOS AppKit 菜单栏应用，使用 WKWebView 展示本机守卫、服务器连接和桌面应用入口。

当前 macOS 版通过一个 SSH 网关同时维护服务器入口、Claude 守卫转发和 Codex 普通代理转发。界面提供连接、断开、更换节点，以及 Codex / Claude 桌面启动按钮。密码在 CCEN 主窗口的原生对话框中输入，不进入 WebView、配置或日志。确认后才启动 OpenSSH，应用通过 Pexpect 的独立 PTY 完成登录。已有的 CCEN 网关连接可以直接被界面监测。

本机配置位于 `~/Library/Application Support/ClaudeConnectionManager/`。服务器配置位于 `~/.ssh/ccen-target.json`，包括平台入口、实际用户、共享家目录和本机密钥路径。固定 SSH 别名是 `ccen`，配置在 `~/.ssh/ccen.conf`，由主 SSH 配置 Include 引入。

## 安装和配置

新 Mac 首次安装、迁移到同一台服务器、准备 SSH 公钥和检查模型登录，见 [换电脑安装教程](../../docs/install-on-another-computer.md)。

下载 [macOS Apple Silicon ZIP](https://github.com/ICtutu-JING/ccen/releases/tag/macos-2026.11.20)，解压后把应用拖到“应用程序”。已经在这台 Mac 上配置过 CCEN，可继续使用应用数据和 SSH 配置。

| 设置 | 这台 Mac 的配置 |
| --- | --- |
| Clash 固定住宅代理 | `127.0.0.1:7895` |
| Clash 普通代理 | `127.0.0.1:7890` |
| 本机守卫和远端 Claude 代理 | `127.0.0.1:17899` |
| 远端 Codex 普通代理 | `127.0.0.1:7897` |
| 固定出口地区 | `US / IAD` |
| 守卫 / 登录 Mac 后启动 | 开启 / 开启 |

首次打开时，在应用生成的 `deployment.json` 中填入自己的固定出口 IP，确认 Clash 监听端口后重新打开。新设备可从“我的服务器 → 添加服务器”填写网关、实际 Linux 用户、家目录和本机私钥路径。CCEN 保存配置并加入 SSH 别名的 Include，随后弹出密码窗口。[服务器字段说明](../../docs/install-on-another-computer.md#3-让新-mac-连接目标-ssh-账户)

## 已有部署的日常使用

1. 启动 Clash 和 CCEN，点击“连接服务器”。在原生密码窗口输入或按 `⌘V` 粘贴；`⌘A` 可全选后重新填写。点击“连接”后才开始 SSH 登录，密码不会保存。取消时保留原连接。
2. 在 Codex 连接设置里启用 ccen；在 Claude 桌面 Code 中选择 ccen 和服务器项目。
3. 换节点时点击“更换节点”，填写服务器地址、用户名和端口，再粘贴当次密码。即使平台复用了相同地址和用户名，该操作也会重新登录并识别实际节点。相同共享家目录可复用工具与配置。

界面依次显示等待密码、登录和通道建立、节点切换、出口核验。失败原因会保留在服务器卡片和运行记录中；检查提示后可再次从“更换节点”填写信息并重试。

远端 Claude 桌面 SSH 会话使用 `~/.claude/settings.json` 中的代理变量。Codex 的远端启动条件 `CODEX_REMOTE_PAYLOAD` 在登录 shell 中启用对应代理变量。CLI 命令入口也保留各自的代理。

## 生命周期

关闭窗口后在菜单栏继续运行。登录自启恢复本机守卫并检查现有服务器连接；需要临时密码时由用户点击连接。退出应用会停止它管理的守卫和 CCEN 网关通道。未实现自动跨节点迁移任务，也不会保存临时密码。

本机守卫每 10 秒核验出口；服务器代理每 30 秒实测。界面显示网络检测结果，不把网络连通等同于账号或模型调用成功。

## 验证记录

已在 Apple Silicon Mac 上构建并安装，实际运行菜单栏界面、登录自启设置、浏览器守卫、共享 SSH 通道、图形换节点表单和桌面应用入口。已从远端核验 Claude 出口及 Codex 授权服务连通性。2026-11-06 已通过应用的“更换节点”入口，在当前有效节点上完成重新认证、替换旧通道、识别共享目录及工具、更新固定入口和出口核验；连接由应用独立建立。Claude 桌面账号登录、首次 SSH 项目会话和模型请求仍需使用者完成。

## 构建

需要 macOS、Python 3.12、与目标架构相同的 Node 24.14.0 和 Xcode Command Line Tools。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
bash build.sh
```

可用 `PYTHON`、`NODE` 指定工具路径。生成应用在 `dist/`，包含 Python 和 Node 运行时；使用 ad-hoc 签名，未做 Developer ID 公证。构建包不附带用户密码、密钥、代理订阅或登录状态。每台 Mac 都需要配置自己的本机代理和 SSH 目标，真实部署文件不随源码分发。
