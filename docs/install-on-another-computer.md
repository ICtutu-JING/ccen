# 在另一台电脑上安装 CCEN

在目标电脑上打开 Codex，选择本机作为任务运行位置。Codex 可以下载和安装适合该机器的 CCEN，填写配置并检查连接。运行安装任务需要本机的文件和网络权限，密码和网页授权由使用者在相应窗口完成。

| 目标电脑 | 入口 |
| --- | --- |
| Apple Silicon Mac，macOS 13.5 或以上 | [下载 macOS ZIP](https://github.com/ICtutu-JING/ccen/releases/tag/macos-2026.11.06.1)，按下文操作。ZIP 内包含 Python 和 Node 运行时。 |
| Intel Mac | 当前 Release 提供 Apple Silicon ZIP。Intel 机器需按 [macOS 构建说明](../macos/manager/README.md#构建) 使用同架构的依赖自行构建和验收。 |
| Windows x64 | 按 [Windows 安装教程](windows.md) 下载、解压并配置。该版本使用已有 SSH 别名和 Linux gate。 |
| Linux | 按 [Linux 部署教程](linux.md) 配置命令行、固定出口 gate 和 wrapper。 |

## 1. 下载并启动 Mac 应用

从仓库 Release 下载 ZIP，完整解压，将 `ClaudeConnectionManager.app` 放入用户的“应用程序”文件夹 `~/Applications`。第一次打开会生成 `~/Library/Application Support/ClaudeConnectionManager/deployment.json`。填写后重新打开应用。

安装包使用 ad-hoc 签名，尚未做 Apple 公证。若 macOS 提示无法验证开发者，使用者应确认是从仓库 Release 获取的应用，再自行决定是否按 [Apple 的打开应用说明](https://support.apple.com/en-hk/102445) 在“系统设置 → 隐私与安全性”里仅对该应用放行。

## 2. 配置新电脑上的代理

先让新 Mac 上的 Clash 或兼容代理运行。固定住宅 HTTP 代理和普通 HTTP 代理需要分别有本机入口。使用旧 Mac 的同一出口时，通过私人渠道迁移或重新填写代理配置。供应商提供的连接地址有时与实际公网出口 IP 不同。

| `deployment.json` 字段 | 如何填写 |
| --- | --- |
| `residential_port` | 新 Mac 上固定住宅 HTTP 代理的监听端口。示例为 `7895`。 |
| `ordinary_port` | 新 Mac 上普通 HTTP 代理的监听端口。示例为 `7890`。 |
| `expected_ip` | 通过住宅代理访问时应看到的固定公网 IPv4。将示例 IP 替换为实际值。 |
| `expected_country`、`expected_colo` | 通过该住宅代理访问 `https://claude.ai/cdn-cgi/trace` 时应看到的 `loc`、`colo`。使用同一代理也要在新电脑核对。 |

可以让新机 Codex 用以下命令检查示例端口，使用其他端口时替换命令中的数字。

```sh
curl --disable -fsS --max-time 15 --noproxy '' --proxy http://127.0.0.1:7895 https://claude.ai/cdn-cgi/trace | awk '/^(ip|loc|colo)=/'
curl --disable -fsS --max-time 15 --noproxy '' --proxy http://127.0.0.1:7890 --output /dev/null --write-out '%{http_code}\n' https://auth.openai.com/.well-known/openid-configuration
```

先核对住宅出口与预期一致，并确认普通代理返回 `200`。只用本机守卫时，在 CCEN 里点“启动守卫”，看到“核验通过”后即可按 [AdsPower 接入说明](adspower.md) 将浏览器代理设为 `127.0.0.1:17899`。

## 3. 让新 Mac 连接已有服务器

1. 准备平台给的网关地址、端口和登录用户名。用平台登录验证 Linux **实际用户名**、家目录的真实路径，以及 Python 3、curl、`codex` 和 `claude` 是否可用。`gateway.user` 是平台登录用的名字，`inner_user` 是进入 Linux 后的账号。可以在服务器上用 `id -un`、`realpath "$HOME"` 和 `command -v python3 curl codex claude` 查看这些值。
2. 新 Mac 使用自己的 SSH 密钥。可让 Codex 创建该用途的 Ed25519 密钥，再通过已授权的服务端入口把新机的 `.pub` 公钥追加到实际 Linux 用户的 `~/.ssh/authorized_keys`，保留原有公钥。私钥保留在新 Mac。
3. 参照 [SSH 节点配置示例](../macos/manager/ccen-target.example.json)，在新 Mac 创建 `~/.ssh/ccen-target.json`。`gateway` 填平台信息，`identity` 填新 Mac 的私钥**文件路径**，`inner_user` 和 `shared_home` 填第一步核实的值。此版本的图形连接从这个文件读取远端目标，`deployment.json` 中的 `remote_enabled` 可以保留示例值 `false`。
4. 保留新机原有的 `~/.ssh/config`，在首个 `Host` 或 `Match` 块前加入 `Include ~/.ssh/ccen.conf`。连接后 CCEN 会生成该文件。若两台 Mac 都连向同一 Linux 节点，请先在旧 Mac 的 CCEN 里点“断开连接”，让新机接管远端 `17899` 和 `7897` 两个监听端口。
5. 重新打开新 Mac 上的 CCEN，点“连接服务器”。核对首次显示的网关主机指纹，在原生窗口中用 **⌘V** 粘贴平台当次密码。看到“已连接”和“链路核验通过”后，再打开 Codex 或 Claude Code。需要自启时，在 CCEN 打开“登录 macOS 后启动”。

服务器需要允许 SSH 端口转发，且网关可访问目标 Linux 环境的 `127.0.0.1:22`。CCEN 读取目标的 ED25519 主机公钥，并使用新 Mac 的密钥登录实际 Linux 用户。第一次连接也会检查远端 PATH 上同时有 `codex` 和 `claude`。已有共享家目录的部署通常可沿用原来的工具和配置。

全新服务器需要先按官方说明安装两个 CLI。让远端 Codex 的启动环境使用普通代理 `http://127.0.0.1:7897`，在远端 `~/.claude/settings.json` 的 `env` 里为 Claude Code 设置 `HTTP_PROXY` 和 `HTTPS_PROXY` 为 `http://127.0.0.1:17899`。合并已有设置，并核对实际启动的进程采用了这些端口。 [OpenAI 远端设置](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host) · [Claude Code 安装](https://code.claude.com/docs/en/quickstart) · [Claude Code SSH 代理设置](https://code.claude.com/docs/en/desktop#set-a-proxy-or-a-ca-certificate-for-ssh-sessions)

## 4. 验收桌面项目和账号

1. 在新 Mac 的 Codex 中进入 **设置 → 连接**，启用 `ccen`，再从该远端主机选择一个真实项目目录。发一条只读取当前主机名和工作目录的请求。看到 Linux 主机的结果，才表示项目确实在服务器上执行。 [OpenAI 远端连接说明](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)
2. 使用 Claude Code 时，在 CCEN 点击“打开 Claude Code”，在 Claude 桌面应用的 **Code** 页面选取 SSH 环境 `ccen`，打开远端目录并做同样的只读验证。 [Claude Code 桌面 SSH 说明](https://code.claude.com/docs/en/desktop#ssh-sessions)
3. 如果用同一个 Linux 用户和共享家目录，有效的远端 Codex 登录通常可复用。如果第一次真实请求报 `401`，让 Codex 检查远端实际 `CODEX_HOME` 和登录状态。需要重新授权时，使用者在浏览器授权。授权成功后仍报 `401`，先确认现有任务状态，再重连远端 Codex 服务使它读到新登录。 [OpenAI 远端登录说明](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)

| 症状 | 首先检查 |
| --- | --- |
| CCEN 阻断住宅出口 | 新 Mac 上固定代理端口、实际 `ip/loc/colo` 和 `deployment.json`。 |
| `Permission denied (publickey)` | 新 Mac 私钥路径、对应公钥是否授权给实际 Linux 用户、网关与内部 SSH 用户是否填反。 |
| 远端转发端口已占用 | 旧 Mac 或其他连接工具是否仍在为同一节点维护相同端口。 |
| CCEN 已连接，Codex 看不到 `ccen` | 新机 `~/.ssh/config` 的 `Include`、生成的 `ccen.conf` 和桌面应用的连接设置。 |
| CCEN 链路通过，Codex 对话返回 `401` | 远端模型登录与工作区授权。 |

## 复制给新机的 Codex

> 我在这台电脑上安装 CCEN，并连接我已有的 Linux 服务器。请使用本机运行环境，从 https://github.com/ICtutu-JING/ccen 下载匹配架构的 Release，按仓库里的 `docs/install-on-another-computer.md` 帮我安装并验证。先检查操作系统、CPU、代理端口、已有 SSH 配置和已安装的软件，再补齐缺少的设置。需要实际网关、Linux 用户、共享家目录或固定出口信息时告诉我缺什么。SSH 密码由我在 CCEN 窗口粘贴，账号授权由我在浏览器完成。请帮我确认 CCEN 的出口检查、Codex 的 `ccen` 连接和远端项目的一次只读请求；告诉我哪些步骤已完成、哪些还需要我点击。
