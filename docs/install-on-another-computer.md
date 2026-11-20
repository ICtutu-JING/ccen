# 在另一台电脑上安装 CCEN

在目标电脑上打开 Codex，选择本机作为任务运行位置。Codex 可以下载和安装适合该机器的 CCEN，填写配置并检查连接。运行安装任务需要本机的文件和网络权限，密码和网页授权由使用者在相应窗口完成。

| 目标电脑 | 入口 |
| --- | --- |
| Apple Silicon Mac，macOS 13.5 或以上 | [下载 macOS ZIP](https://github.com/ICtutu-JING/ccen/releases/tag/macos-2026.11.20)，按下文操作。ZIP 内包含 Python 和 Node 运行时。 |
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

## 3. 让新 Mac 连接目标 SSH 账户

新电脑可以使用另一套 SSH 账户。先从新电脑登录新的平台入口，核实实际 Linux 用户和家目录。平台登录名变化时，实际 Linux 用户有可能仍相同。如果实际用户或家目录不同，请将新机作为独立部署，使用新账户自己的目录、公钥授权、项目以及远端 Codex 登录配置。

1. 准备平台给的网关地址、端口和登录用户名。用平台登录验证 Linux **实际用户名**、家目录的真实路径，以及 Python 3、curl、`codex` 和 `claude` 是否可用。`gateway.user` 是平台登录用的名字，`inner_user` 是进入 Linux 后的账号。可以在服务器上用 `id -un`、`realpath "$HOME"` 和 `command -v python3 curl codex claude` 查看这些值。
2. 新 Mac 使用自己的 SSH 密钥。可让 Codex 创建该用途的 Ed25519 密钥，再通过已授权的服务端入口把新机的 `.pub` 公钥追加到实际 Linux 用户的 `~/.ssh/authorized_keys`，保留原有公钥。私钥保留在新 Mac。
3. 新机打开 CCEN，在 **我的服务器 → 添加服务器** 填写平台地址、平台登录用户名、端口、实际 Linux 用户、远端家目录和新 Mac 的私钥**文件路径**。这些字段对应 [SSH 节点配置示例](../macos/manager/ccen-target.example.json)。若新机的 CCEN 已经连过另一个实际 Linux 用户，先退出并备份原 `~/.ssh/ccen-target.json`，再更新该文件。已连接过的配置使用“更换节点”时，仍要求实际 Linux 用户和家目录与配置一致。
4. 点击“保存并连接”，在原生窗口用 **⌘V** 粘贴当次密码，核对首次提示的网关主机指纹。CCEN 会保存 `~/.ssh/ccen-target.json`，并加入管理 `ccen` 别名所需的 SSH Include。如果首次验证失败，可点“编辑服务器”修正账户、目录或密钥。如果两台电脑的连接在同一 Linux 网络环境中争用远端 `17899` 或 `7897`，确认旧连接没有任务依赖后再从旧电脑断开。
5. 看到“已连接”和“链路核验通过”后，再打开 Codex 或 Claude Code。需要自启时，在 CCEN 打开“登录 macOS 后启动”。

服务器需要允许 SSH 端口转发，且网关可访问目标 Linux 环境的 `127.0.0.1:22`。CCEN 读取目标的 ED25519 主机公钥，并使用新 Mac 的密钥登录实际 Linux 用户。第一次连接也会检查远端 PATH 上同时有 `codex` 和 `claude`。已有共享家目录的部署通常可沿用原来的工具和配置。

对于全新服务器或新 Linux 用户，先用该账户检查两个 CLI。缺少哪个就按官方说明安装哪个，确保新账户能在其登录 shell 中调用。让远端 Codex 的启动环境使用普通代理 `http://127.0.0.1:7897`，在该用户的远端 `~/.claude/settings.json` 的 `env` 里为 Claude Code 设置 `HTTP_PROXY` 和 `HTTPS_PROXY` 为 `http://127.0.0.1:17899`。合并已有设置，并核对实际启动的进程采用了这些端口。 [OpenAI 远端设置](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host) · [Claude Code 安装](https://code.claude.com/docs/en/quickstart) · [Claude Code SSH 代理设置](https://code.claude.com/docs/en/desktop#set-a-proxy-or-a-ca-certificate-for-ssh-sessions)

## 4. 验收桌面项目和账号

1. 在新 Mac 的 Codex 中进入 **设置 → 连接**，启用 `ccen`，再从该远端主机选择一个真实项目目录。发一条只读取当前主机名和工作目录的请求。看到 Linux 主机的结果，才表示项目确实在服务器上执行。 [OpenAI 远端连接说明](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)
2. 使用 Claude Code 时，在 CCEN 点击“打开 Claude Code”，在 Claude 桌面应用的 **Code** 页面选取 SSH 环境 `ccen`，打开远端目录并做同样的只读验证。 [Claude Code 桌面 SSH 说明](https://code.claude.com/docs/en/desktop#ssh-sessions)
3. 检查目标 Linux 用户的远端 Codex 登录状态。新账户可以使用你已有的 ChatGPT 账号授权，登录状态保存在该 Linux 用户自己的 Codex 配置中。若该用户已有有效授权，可直接验收。若未登录、授权过期，或请求报 `401`，让 Codex 检查远端实际 `CODEX_HOME`，必要时由使用者在浏览器授权。授权成功后仍报 `401`，先确认现有任务状态，再重连远端 Codex 服务使它读到新登录。 [OpenAI 远端登录说明](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)

| 症状 | 首先检查 |
| --- | --- |
| CCEN 阻断住宅出口 | 新 Mac 上固定代理端口、实际 `ip/loc/colo` 和 `deployment.json`。 |
| `Permission denied (publickey)` | 新 Mac 私钥路径、对应公钥是否授权给实际 Linux 用户、网关与内部 SSH 用户是否填反。 |
| 远端转发端口已占用 | 旧 Mac 或其他连接工具是否仍在为同一节点维护相同端口。 |
| CCEN 已连接，Codex 看不到 `ccen` | 新机 `~/.ssh/config` 的 `Include`、生成的 `ccen.conf` 和桌面应用的连接设置。 |
| CCEN 链路通过，Codex 对话返回 `401` | 远端模型登录与工作区授权。 |

## 复制给新机的 Codex

> 请在这台电脑上安装 CCEN。我要使用另一套 SSH 账户。请使用本机运行环境，从 https://github.com/ICtutu-JING/ccen 下载匹配架构的 Release，按仓库里的 `docs/install-on-another-computer.md` 操作。用我提供的新 SSH 入口核对实际 Linux 用户和家目录，为新电脑配置公钥授权，检查新账户能否运行 Codex 和 Claude Code，需要时再安装缺少的工具和配置远端账号。SSH 密码由我在 CCEN 窗口粘贴，账号授权由我在浏览器完成。最后确认代理出口、`ccen` 连接和一次只读的远端项目请求。
