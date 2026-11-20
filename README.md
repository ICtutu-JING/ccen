# CCEN：Claude / Codex 连接与固定出口防护

CCEN 包含 macOS 菜单栏连接管理器、Windows 托盘连接管理器，以及 Linux 固定出口 gate 和 Claude 网络 namespace。

- [下载 macOS Apple Silicon 版](https://github.com/ICtutu-JING/ccen/releases/tag/macos-2026.11.20) · [源码和配置](macos/manager/README.md)
- [下载 Windows x64 便携版](https://github.com/ICtutu-JING/ccen/releases/tag/v2026.10.30) · [源码和配置](windows/manager/README.md)

macOS 版支持在图形界面连接服务器、粘贴当次 SSH 密码并更换节点，Codex 和 Claude Code 共用 `ccen` 入口。配置示例采用本机使用的端口，实际代理出口、服务器和密钥路径由使用者在本机填写。

CCEN 不是 Anthropic、OpenAI 或 AdsPower 的官方产品。

## 从哪里开始

| 需求 | 阅读入口 |
| --- | --- |
| 让 Codex 帮你在另一台电脑上安装和验收 | [换电脑安装教程与可复制提示词](docs/install-on-another-computer.md) |
| 构建和使用 macOS 管理器 | [macOS 软件与构建说明](macos/manager/README.md) |
| 下载或构建 Windows 管理器 | [Windows 软件](docs/windows.md)、[源码与配置](windows/manager/README.md) |
| 建立完整链路 | [部署路线](docs/onboarding.md)、[代理与 SSH](docs/proxy-and-ssh.md)、[Linux](docs/linux.md) |
| 接入 AdsPower | [浏览器配置](docs/adspower.md) |
| 配置 VS Code 与不同 Codex 后端 | [编辑器](docs/editors.md) |
| 理解防护范围与验证现状 | [架构](docs/architecture.md)、[边界](docs/security.md)、[验收](docs/verification.md)、[交付状态](docs/completeness.md) |

## Windows 软件

- 一个托盘窗口分别显示浏览器守卫、Claude 住宅连接和 Codex 普通代理状态。
- SSH 子进程隐藏运行；关闭窗口后在托盘继续维护，暂停自动恢复保留现有连接。
- 接管精确匹配的专用转发；确认会话只包含 sshd 后，处理远端遗留占端口问题。
- 固定住宅入口为 7899，浏览器守卫为 17899；Codex 通过普通代理 7897。
- 提供 Python 依赖版本、Node 锁文件、部署配置示例和独立构建脚本。

## 固定出口策略

1. Linux gate 17898 的专用上游是 7899。住宅链失败时不自动改走普通代理或 DIRECT。Codex 普通代理是独立链路。
2. Linux gate 分别检查 ipify、Cloudflare IP/国家、Anthropic CF-Ray 节点。这些是周期抽样，不代表逐包持续观测。
3. 只有通过 ccen 或正确 wrapper 启动的 Claude 进程树具有此处的 Linux namespace；其他入口分别验收。
4. Windows 浏览器守卫首次完整核验后才放行。身份不符时断开；成功核验后的独立探测网络错误显示告警，固定上游继续转发。
5. Codex 代理托管不等于强制网络隔离；界面网络状态不等于模型已经回复。

## 目录和交付状态

- [macos/manager](macos/manager)：macOS 菜单栏应用、图形切换节点、配置示例和构建入口。
- [windows/manager](windows/manager)：Windows GUI、Node 守卫、SSH 维护、部署示例、构建入口。
- bin、libexec、systemd：Linux CLI、gate、namespace、PID1 和可选宿主通道。
- examples：Mihomo、SSH、编辑器无凭据示例。
- tools/render-linux.py：生成 Linux 私人部署目录。
- docs：[原理、部署和验证记录](docs/inventory.md)。

Linux 模板仍须先渲染；Windows 真实部署配置留在各自设备并由 Git 忽略。源码交付、构建成功、维护者设备观测与新设备验收分别记录。
