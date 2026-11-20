# 从零部署路线

## 1. 先选择目标

本项目涉及三个执行位置：Windows 工作站、Linux 宿主、Linux 内部的 Claude 私有网络 namespace。`127.0.0.1` 在三个位置分别指各自的本机，配置时必须先确认命令在哪运行。

默认路线是“Windows 专用代理 → 连接管理器维护 SSH → Linux gate → Claude wrapper”。Windows 软件源码和便携包已经收录，见 [Windows 软件](windows.md)。只部署 Linux 时也可以使用手动 SSH；浏览器 profile、托盘、自启和其他设备仍分别验收。

## 2. 准备自己的材料

先通过正常 Git 认证取得仓库，记录当前提交。仓库仍为私有时，需要所有者已授权的账号；不要将访问令牌嵌入 clone URL 或写入文档。Linux 的新目录示例：

```bash
mkdir -p "$HOME/src"
git clone https://github.com/ICtutu-JING/ccen.git "$HOME/src/ccen"
cd "$HOME/src/ccen"
git rev-parse HEAD
```

Windows 获取同一份代码可使用：

```powershell
git clone https://github.com/ICtutu-JING/ccen.git "$env:USERPROFILE\source\ccen"
Set-Location "$env:USERPROFILE\source\ccen"
git rev-parse HEAD
```

已有 checkout 时先检查自己的未提交修改，再决定更新方式，不要用覆盖目录或强制重置替代正常更新。Linux 工作区应位于持久目录；wrapper 会替换 `/tmp` 和 `/run`，不应从这些目录中的项目启动受保护进程。

| 参数/软件 | 从哪里获得 | 用在哪里 |
| --- | --- | --- |
| 仓库读取权限 | 仓库所有者授权；公开副本则按其访问方式 | 获取源码，与服务器/服务账号权限独立 |
| 固定出口代理 | 使用者自行配置可用服务 | Windows 专用 listener 的出站 |
| 代理服务器、端口、协议、认证 | 自己的代理服务配置 | 私人 Mihomo 配置，不提交 Git |
| 预期公网 IPv4 | 通过专用入口实际观测，并与代理服务约定核对 | renderer `--expected-ip`；不一定等于代理服务器地址 |
| 预期国家 | 专用入口的 Cloudflare trace `loc` | `--country` |
| Anthropic POP | 通过同一入口向 `api.anthropic.com` 请求所得 CF-Ray 后缀 | `--anthropic-colo`；不能用 Cloudflare 官网 POP 代替 |
| Linux HOME / UID | 在目标 Linux 执行 `printf '%s\n' "$HOME"`、`id -u` | 渲染绝对路径、runtime 和所有权检查 |
| Linux SSH alias、主机、公钥认证 | 使用者自己的服务器和已核验 host key | Windows SSH 连接与反向转发 |
| Claude CLI 和账号 | 官方软件与使用者自己的登录 | Linux 实际模型请求 |
| locale / namespace / systemd 支持 | 目标 Linux 系统及个人 locale 目录 | wrapper 与 gate 运行环境 |
| 编辑器扩展 / AdsPower | 各自的软件安装与版本记录 | 分组件接入和验收 |

POP 是网络边缘标识；固定 POP 是本项目的路由约束，不能证明住宅属性或账号状态。时区和 locale 也是运行参数，不是出口身份。当前参数范围与限制在 [Linux](linux.md) 中明确。

## 3. 顺序与每步完成条件

| 阶段 | 运行位置 | 操作 | 必须看到的证据 | 失败时停在哪 |
| --- | --- | --- | --- | --- |
| A 获取代码 | 开发/部署设备 | clone/fetch 固定提交，阅读缺件与边界 | 版本明确，知道哪些能力未交付 | 先解决访问或材料问题 |
| B 固定上游 | Windows | 合并自己的代理配置，核对 `7899` | 实际 IP/国家/API POP，非只有端口 | 代理和前置链路 |
| C 普通 SSH | Windows → Linux | 人工登录、核验 host key、准备认证 | 普通 SSH 成功，密钥可供隧道使用 | SSH/账号/主机信任 |
| D 反向隧道 | Windows → Linux | 专用 `-R`，保持该终端运行 | Linux `7899` 实际请求返回同一出口 | 转发规则或隧道所有权 |
| E 渲染 | Linux | 依赖/locale 预检，生成新 staging | 全部参数和 manifest 正确，无未替换 token | 参数、依赖或文件材料 |
| F 安装 | Linux | 备份、按明确文件表安装、启用 gate | gate service 与近期完整检查通过 | 服务/上游/runtime |
| G 隔离验收 | Linux | 同一 wrapper 中核对 namespace、代理成功和直连失败 | 三项同时成立 | bwrap/namespace/wrapper |
| H 应用验收 | 各自应用 | CLI、图形插件、Codex 分开验证 | 各自的进程与请求证据 | 对应应用启动路径 |
| I 失败与恢复 | 自己的空闲测试环境 | 正常→断链→恢复、错误预期值 | 行为与状态机一致，无改换出口 | 保留失败，修正后重验 |
| J 日常使用 | 已验收设备 | 保存私人收据和版本 | 明确维护及升级责任 | 版本变化后重验相关层 |

命令按 [代理与 SSH](proxy-and-ssh.md)、[Linux](linux.md)、[编辑器](editors.md)、[分层验收](verification.md) 执行。A–I 是依赖顺序，不是允许跳过失败的建议。服务器没有 Windows 工作站时，可由使用者维护等价的固定专用上游，但必须自行验证其协议和路由；文档不把未测试的替代部署算作已支持环境。

## 4. Windows App 与浏览器的独立分支

先完成 [Windows 源码交接](windows.md) 的源文件与依赖检查，再构建、配置、验证 App。随后才按 [AdsPower](adspower.md) 将独立 profile 接入守卫。不要把 AdsPower 临时指向原始 `7899` 后记录成“浏览器守卫已通过”：那样只能验证原始代理，绕过了待验收的 `17899` 组件。

浏览器登录、VS Code webview、Remote Extension Host、Claude 子进程和 Codex app-server 是不同流量面。需要保护哪个入口，就为哪个入口保留独立验收记录。

## 5. 首次验收后保存什么

私人部署记录至少包含：仓库提交、渲染清单哈希、实际软件版本、在哪台设备执行、各组件完成时间、正常/失败路径结果，以及没有启用的可选能力。不要保存或发布完整环境变量、认证头、Cookie 或私钥。

手动隧道的维护者就是启动它的使用者。关闭终端、注销 Windows、睡眠或网络变化都可能中断它；自动恢复属于另一个需要验收的功能，不会因 gate 自动重试而自然获得。
