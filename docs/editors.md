# VS Code、Claude Code 与 Codex 插件的网络防护

本页记录这套环境实际使用的连接方式，以及新环境部署时必须重新核验的边界。适用于 Windows 桌面 VS Code 连接 Linux Remote-SSH 的方案；本仓库的 bubblewrap 包装器运行在 Linux 上。示例中的端口是本项目约定；`YOUR_USER`、服务器地址和固定出口必须换成使用者自己的配置。不要复制他人的登录令牌、浏览器资料目录或代理密码。

## 1. 先分清三个执行位置

```text
Windows 上的 VS Code 窗口 / Webview / 本地 Extension Host
                  ├─ 外部登录浏览器 → 它自己的代理配置
                  │ SSH 编辑器连接
                  ▼
Linux 上的 VS Code Server / Extension Host
                  │ 启动插件后端
                  ├─ Claude 图形模式 → claude-net-sandbox → 隔离网络 → 17898 闸门
                  └─ Codex app-server → HTTP(S)_PROXY=17898（本次观察到的配置）
                                                                        │
                                              SSH 回送的上游代理 → 固定出口
```

`127.0.0.1` 始终指当前进程所在的机器。远程设置中的 `127.0.0.1:17898` 是 Linux 服务端的闸门；Windows AdsPower 使用的本机守卫端口属于另一条入口。不要在远程插件设置里直接填 Windows 的浏览器入口端口。

Remote-SSH 窗口可以同时有本地、Web 和远程 Extension Host；扩展的实际位置由安装位置、扩展能力及其声明决定。左下角显示 `SSH: ...` 不能证明每个扩展都在服务器运行。先在扩展面板确认目标扩展是否安装到该 SSH 主机，再通过运行扩展列表、进程树和后端可执行文件核对。[VS Code Extension Host](https://code.visualstudio.com/api/advanced-topics/extension-host)、[Remote-SSH 扩展管理](https://code.visualstudio.com/docs/remote/ssh#managing-extensions)

远程插件后端走代理，不足以证明 Windows 登录浏览器、Webview、扩展自身的每一次请求也走同一条链路。登录可能打开默认浏览器；默认浏览器不会因为 AdsPower 的另一个 profile 配置了代理就自动继承它。检查实际打开的浏览器、profile 和出口，再完成登录。

| 使用方式 | 配置和进程应在哪里核对 | 本页模板的适用范围 |
| --- | --- | --- |
| Windows VS Code + Linux Remote-SSH，扩展运行在远程 | 远程 Machine settings、Linux Extension Host 及其后端 | 本页的主要部署方式 |
| Windows 本地 VS Code，扩展运行在本地 | Windows User settings、本地后端与本地入口 | 不能使用 Linux 绝对路径或假定 Windows 有 `17898` |
| Remote-SSH 窗口中的本地扩展 / Webview | Windows 侧进程与它实际使用的网络设置 | 需要独立验收；远程包装器不覆盖这些进程 |
| 远程集成终端里的 CLI | 终端 shell 的启动环境，以及实际执行的 CLI | 终端中的 `ccen` 与图形插件是两个入口 |
| 独立桌面 App、其他 app-server、WSL、容器或云端会话 | 各自运行主机、启动者、配置与网络边界 | 本次未为这些启动方式完成同等保护验收 |

`app-server` 是后端进程角色，单看这个名字无法判断它由 IDE、桌面应用还是另一条会话启动。必须结合父进程和实际二进制定位；不要把所有同名进程视为同一个插件。

## 2. 当前方案的覆盖范围

| 入口或组件 | 当前使用的控制 | 能说明什么 | 需要保留的边界 |
| --- | --- | --- | --- |
| `ccen` 启动的 Claude CLI | 启动检查、固定出口闸门、`claude-net-sandbox` | 按该入口进入的进程树有网络命名空间隔离 | 直接运行其他二进制不自动进入该入口 |
| Claude Code 图形插件的 Claude 子进程 | `claudeCode.claudeProcessWrapper` | 插件调用包装器，再运行它传入的 Claude 可执行文件 | 包装器不包住整个 VS Code Extension Host |
| VS Code 远程扩展的代理配置 | `http.proxy`、`http.proxySupport`、环境变量 | 为遵守这些配置的请求提供代理地址 | 配置项本身不是防火墙，不能阻止程序忽略代理或使用其他协议 |
| 本次观察到的 Codex 插件后端 | 插件从 `http.proxy` 生成 `HTTP_PROXY`、`HTTPS_PROXY` | 后端进程确实收到闸门地址 | 未发现与 Claude 等价的强制网络隔离包装器 |
| 其他 Codex CLI / app-server | 取决于各自启动环境 | 需要逐个进程核验 | 不能因一个插件进程配置正确，就认定全部 Codex 会话受保护 |
| Windows 登录浏览器、AdsPower | Windows 本机守卫和浏览器配置 | 由本机侧独立核验 | 不由 Linux 的 Remote Settings 自动覆盖 |

网络隔离也不是文件系统只读沙箱。当前 Linux 包装器保留工作文件写入能力，并对防护脚本、部分配置和控制目录增加只读或遮蔽挂载；允许的固定 SSH relay、host runner 等能力有各自的权限边界。

## 3. 远程 VS Code 配置

### 安装前提

先完成 [Linux 部署](linux.md) 和 [专用代理与 SSH](proxy-and-ssh.md)：服务端 `7899` 是实际可用的专用上游，`claude-ip-guard enforce` 成功，包装器及其 libexec 依赖已经安装，systemd 用户 manager 和 bubblewrap 可用。只安装编辑器扩展不会创建这些组件。

Windows 侧需要 VS Code、Remote-SSH 和可用的 OpenSSH；应先用自己的身份完成服务器 host key 核验和普通 SSH 登录，再连接 Remote-SSH。编辑器 SSH 会话与代理反向隧道可以是不同会话，能编辑远程文件不等于代理隧道存在。[Remote-SSH 安装与连接](https://code.visualstudio.com/docs/remote/ssh)

在扩展面板确认扩展 ID 和目标安装位置。本次检查的 Linux 包为 `anthropic.claude-code` 2.1.301 与 `openai.chatgpt` 26.1007.21434；其 `engines.vscode` 分别声明 `^1.94.0` 与 `^1.96.2`。这些是所检查包的约束，不能外推为以后所有版本的最低要求。版本和平台应以实际安装包为准。

图形 Claude 插件会使用它选择的 Claude 二进制；独立的 `~/.local/bin/claude` 则由 CLI 入口使用，两者可能不同版本。扩展安装包自带二进制并不等于独立 CLI 已安装，CLI 已安装也不等于插件已经运行在正确主机。

本仓库包装器要求首个参数是存在、可执行的绝对路径。对于本次检查的图形插件，需确认对应平台的 bundled binary 实际存在；扩展未提供二进制时，不能只配置本包装器就假定会自动找到独立 CLI，此处应报错并停止，先解决平台与二进制路径。

### 合并设置

1. 在 VS Code 连接目标主机后，打开 **Preferences: Open Remote Settings (JSON)**，确认是目标 SSH 主机的远程设置。本次标准 Linux 安装对应 `~/.vscode-server/data/Machine/settings.json`；其他发行版或安装方式可能不同，以编辑器打开的文件为准。
2. 优先使用 renderer 生成的 `config/vscode-machine-settings.json`，或参考 [`examples/vscode-remote.settings.json`](../examples/vscode-remote.settings.json) 合并相关键。保留原有无关设置，不替换整份 Machine settings。
3. 把包装器改成目标用户的真实绝对路径。不要保留 `YOUR_USER`，也不要假定扩展会展开 `~` 或 `$HOME`。
4. 确认有效的 `claudeCode.useTerminal` 是 `false`，使用图形模式。检查 User、Remote、Workspace 和 Profile 的现有值，不能只检查示例文件。
5. 重载窗口，关闭并重新打开相关插件会话，再做第 7 节验收。记录当前窗口对应的后端 PID；磁盘配置更新不会自动改变已经启动的进程。

本次已安装包把 `claudeCode.claudeProcessWrapper`、`claudeCode.environmentVariables` 声明为 `machine` scope；不要把主机绝对路径和个人网络参数写进共享 `.vscode/settings.json`。其他设置的覆盖顺序和 scope 也可能不同，Settings UI 中的有效值、扩展输出和实际进程是最终检查对象。Remote-SSH 的 Remote 设置可覆盖 User 设置，但可覆盖项还会受到 Workspace 设置影响。[Remote-SSH 主机设置](https://code.visualstudio.com/docs/remote/ssh#ssh-host-specific-settings)

各配置的作用：

- `http.proxy` 指向服务端闸门 `http://127.0.0.1:17898`。
- 当前 VS Code 安装声明中，`http.useLocalProxyConfiguration=false` 表示远程 Extension Host 不复用本地代理配置，允许分别配置本地和远程地址；它只适用于远程设置。
- `http.proxySupport=override` 表示启用扩展代理支持并覆盖相关请求选项。这是 VS Code 支持的网络栈行为，不是内核过滤规则。
- `http.proxyStrictSSL=true` 保留代理证书验证。检查原有有效值；本次 Codex 扩展实现会在它为 `false` 时给后端设置 `NODE_TLS_REJECT_UNAUTHORIZED=0`。不要用关闭验证处理证书错误；需要企业 CA 时按软件的 CA 配置处理，并独立核验。
- `http.noProxy` 与 `NO_PROXY` 仅保留回环地址，不添加 `*` 或外部业务域名。
- `claudeCode.useTerminal=false` 选择图形插件入口；设置为 `true` 后必须重新核验启动路径，不能沿用图形 wrapper 的验收结果。
- `claudeCode.environmentVariables` 给 Claude 子进程显式传入 HTTP(S) 代理。
- `claudeCode.claudeProcessWrapper` 让插件以包装器启动 Claude。扩展传入的首个参数是它选择的 Claude 可执行文件，包装器必须保留后续参数、标准输入输出和退出码。

示例 JSON 不设置地区、语言或时区；Linux 包装器另外设置了运行 locale，详见 Linux 部署。示例也不关闭 TLS 验证。地区值和 locale 不能证明出口正确；出口应以网络校验为准。

Claude Code 官方说明支持 HTTP/HTTPS 代理环境变量，且不支持直接使用 SOCKS 代理。因此 Claude 环境变量应填写本项目提供的 HTTP 入口，即便更上游使用了其他代理协议。官方还说明 `environmentVariables` 作用于 Claude 进程，`claudeProcessWrapper` 用于启动 Claude 进程。[Claude 网络配置](https://code.claude.com/docs/en/network-config)、[Claude VS Code 设置](https://code.claude.com/docs/en/vs-code#extension-settings)

VS Code 自身与扩展的网络行为存在区别；应把这些键看作代理设置，而不是所有扩展流量都无法绕过的保证。[VS Code 网络配置](https://code.visualstudio.com/docs/setup/network)

## 4. Extension Host 的启动环境

本机已有的 `~/.vscode-server/server-env-setup` 设置了以下变量。只有需要把代理配置扩展到远程 VS Code Server 的启动环境时，才在目标主机的同名文件中合并这一段；它是服务端的配置，不是仓库内的项目配置，作用范围也大于 Claude 插件自身。

```sh
export http_proxy=http://127.0.0.1:17898
export https_proxy=http://127.0.0.1:17898
export HTTP_PROXY=http://127.0.0.1:17898
export HTTPS_PROXY=http://127.0.0.1:17898
unset all_proxy ALL_PROXY
export no_proxy=localhost,127.0.0.1,::1
export NO_PROXY=localhost,127.0.0.1,::1
```

文件存在不等于当前进程已继承。应重新连接并检查实际 Extension Host / 插件后端的环境；已经运行的进程不会因为磁盘文件变化自动更新。若重连后仍是旧进程，安排可接受的窗口再重启 VS Code Server，避免打断正在进行的其他会话。

这也可能让集成终端继承代理变量，而当前 `ccen` 有“普通终端不可预置全局代理”的检查。如果确认变量仅来自上述配置，可只对这一条启动命令清除继承值，由 `ccen` 完成检查后重新注入受控代理：

```sh
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY ccen
```

环境变量也只是给支持它们的网络库提供配置。需要阻止直接网络访问时，应核验网络命名空间或操作系统防火墙，而不能只检查变量。

## 5. Claude 的两个容易遗漏的入口

### 直接输入 `claude`

本次本机检查发现 `~/.local/bin/claude` 仍是官方安装的二进制符号链接。它不会自动经过 `ccen` 的启动检查与外层网络隔离。`~/.claude/settings.json` 虽然有代理环境变量，但变量不等价于强制隔离。

使用本仓库部署方案时，交互 CLI 入口应为 `ccen`；VS Code 图形插件应配置上述包装器。不要为了包装 CLI 而覆盖官方管理的安装符号链接。需要额外的同名启动器时，应使用单独的目录及明确的真实二进制路径，避免递归调用。

### 插件的终端模式

本次检查的 Claude 2.1.301 扩展代码中，图形入口通过 `Zk` 读取 `claudeProcessWrapper` 并附上 bundled binary；Linux 终端入口则由 `G64` / `V64` 构造 `claude ...` 命令。由此不能把 `useTerminal=true` 当成仍经过图形包装器：在本机的 CLI 符号链接配置下，它会落到上述直接启动路径。该判断来自所检查版本的实现，更新后应重查。

需要终端界面时，在普通远程集成终端显式运行 `ccen` 并核验它的 namespace；不要通过切换插件终端模式来代替这一步。手工运行 `ccen` 成功，也不能反向证明图形插件已使用 wrapper。

### 后台代理、更新后重启和独立启动的进程

Claude 新版本另有用户级 `processWrapper` / `CLAUDE_CODE_PROCESS_WRAPPER`，用于其自行创建的后台进程。它与 VS Code 的 `claudeCode.claudeProcessWrapper` 是两套配置。

本次检查没有发现本机用户设置启用前者，因此不能仅凭 VS Code 包装器宣称所有后台启动路径都覆盖。不要把现有 `claude-net-sandbox` 路径直接填进去就视为完成：官方后台 launcher 对 `exec`、嵌套调用、继承环境和启动时限有额外要求，需单独适配和验证。[Claude corporate launcher](https://code.claude.com/docs/en/corporate-launcher)

## 6. Codex 插件：当前是代理配置层

本节只描述实际安装包和进程证据，不假定其他版本具有相同行为。

- 本次检查的两个已安装版本，其扩展代码均读取 VS Code `http.proxy`，并给插件启动的后端设置 `HTTP_PROXY`、`HTTPS_PROXY`。
- 本次运行中的一个插件后端确实收到 `http://127.0.0.1:17898`。这证明该进程的代理参数正确，不能单独证明所有请求都被操作系统强制限制。
- 同机还有使用其他代理地址或没有代理环境变量的 Codex app-server。它们属于不同启动链路，不能计入这一个插件的防护结论。
- 未发现本机给 Codex 配置与 Claude 同级别的网络命名空间包装器。不要在文档或验收中把 Codex 标成“全部流量强制固定出口”。

安装包声明的 `chatgpt.cliExecutable` 为 **DEVELOPMENT ONLY**，属于 application scope 的受限设置，并提示手工设置可能影响插件工作。本项目不把它推荐为通用的强制代理或包装器配置入口；在远程机器设置里填入它也不构成可移植方案。

官方 OpenAI 文档说明 app-server 用于支撑包括 VS Code 扩展在内的客户端；这说明了后端角色，不规定本机实际进程的代理参数。扩展安装入口见 [Codex IDE 文档](https://learn.chatgpt.com/docs/codex/ide)，后端角色见 [Codex app-server 文档](https://learn.chatgpt.com/docs/app-server)。本节的代理映射和配置 scope 仍以所检查的安装包及运行进程为证据。

还要检查继承环境：本次看到的映射只生成 `HTTP_PROXY`、`HTTPS_PROXY`，不能据此认定 `http.noProxy` 会变成后端的 `NO_PROXY`。既有的 `NO_PROXY=*`、域名豁免、冲突的小写代理或 `ALL_PROXY` 都需单独排查。不要将完整 Extension Host 环境粘贴到 issue；按第 7 节仅查看允许的变量。必要时调整自己的启动环境并重启对应后端，再重新验证。

使用者应先按第 3 节配置代理，再核验实际后端的启动环境和请求出口。如果要求与 Claude 相同的不可直连能力，还需要针对 Codex 启动链路单独实现、验证网络隔离；当前方案尚未交付这一层能力。独立桌面应用、CLI、其他远程主机或委派到外部环境的工作应另建验收记录，不复用这个 IDE 后端的结论。

## 7. 验收与更新后复核

### 为每个入口建立独立记录

| 检查对象 | 至少记录什么 | 不能互相代替的证据 |
| --- | --- | --- |
| gate | 预期出口、daemon PID、boot/hostname、最近成功时间、reason、TCP/UDS 状态 | 服务 active 不代表刚刚通过检查；degraded 的 allowed 也不是新启动验收通过 |
| CLI `ccen` | 实际二进制、scope、namespace、一次真实模型回复 | CLI 成功不能证明图形插件或后台会话 |
| Claude 图形插件 | 运行位置、扩展及 bundled binary 版本、有效设置、子进程 PID、namespace、真实模型回复 | 包装器文件存在不能证明当前窗口用了它 |
| Codex 插件 | 当前窗口对应的父子进程、二进制、代理变量、实际请求与断链结果 | 代理变量正确不能证明强制隔离；另一条 app-server 成功不能替代 |
| Windows 登录浏览器 / AdsPower | 实际浏览器和 profile、监听协议、浏览器出口与阻断结果 | 远程 gate 探测不能替代浏览器的真实路径 |

先运行 `claude-ip-guard status`，再按需要运行 `check` 和 `enforce`。`check` 只对上游执行一次真实探测，不开放闸门；`enforce` 可能启动服务并请求刷新，只有满足 guard 的新鲜成功状态才返回通过。`check` 成功本身不证明插件已接入这个 gate。

在图形 Claude 插件新开会话，按运行扩展列表和进程树找到真正的 Claude 子进程，确认在 `claude-net-*` scope 中且网络 namespace 与宿主不同。再完成一次短的真实模型请求；namespace、成功代理请求和 [无代理直连失败检查](verification.md#namespace-无代理直连检查) 应一起判断。仅看到 namespace 不同，不能排除整个测试进程都无法联网。

Codex 要从当前窗口的 Extension Host 向下追踪 app-server；不要把同用户所有 `codex` 进程批量当作目标，也不要为找 PID 输出含令牌的完整命令行。Linux 上可以只读查看选定 PID 的少量字段，例如：

```bash
# 替换为已确认属于该窗口的 Linux 后端 PID；不会启动/停止任何服务。
CCEN_BACKEND_PID=12345 python3 - <<'PY'
import os
from pathlib import Path
from urllib.parse import urlsplit

pid = int(os.environ["CCEN_BACKEND_PID"])
proc = Path("/proc") / str(pid)
if proc.stat().st_uid != os.getuid():
    raise SystemExit("请选择当前用户拥有的后端进程")
print("pid:", pid)
print("exe:", os.readlink(proc / "exe"))
print("backend net:", os.readlink(proc / "ns/net"))
print("inspection shell net:", os.readlink("/proc/self/ns/net"))
for line in (proc / "status").read_text().splitlines():
    if line.startswith("PPid:"):
        print(line)
allowed = {"http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"}
observed = {}
for entry in (proc / "environ").read_bytes().split(b"\0"):
    key, sep, value = entry.partition(b"=")
    name = key.decode(errors="replace")
    if sep and name in allowed:
        observed[name] = value.decode(errors="replace")
for name in sorted(allowed):
    value = observed.get(name)
    if value is None:
        print(name + "=<unset>")
    elif name.lower() == "no_proxy":
        # Do not dump internal domains into logs or a shared issue.
        print(name + "=" + (value if value in ("", "*", "localhost,127.0.0.1,::1")
                            else "<已设置；请在本机检查豁免条目>"))
    else:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"} or not parsed.hostname:
                raise ValueError("invalid proxy endpoint")
            endpoint = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            print(name + "=" + endpoint)  # omit username/password/path/query
        except ValueError:
            print(name + "=<格式异常；请在本机检查>")
PY
```

在普通宿主远程终端运行检查时，Claude 受保护子进程应显示不同的网络 namespace；相同 namespace 说明没有这层隔离。检查进程也处在某个 sandbox 时，应先确认比较基准，不能机械解读 inode。`/proc` 权限或进程退出可能使检查失败；失败结果不能写成通过。环境值只是读取到的启动环境，不能替代请求观测；输出中的本机路径也应留在私人记录中。

对 Codex 分别完成真实模型请求和实际网络路径检查，结论写清“参数已检查”“请求已通过指定链路”与“已验证无法直连”三个层次。由 agent 执行 `curl` 只能验证该工具子进程，不能单独证明 app-server 自身的模型流量。需要结合该后端的出站连接、代理转发日志及时间戳建立对应关系；没有对应证据时只报告已检查参数。

### 故障与更新

故障注入应在自己的隔离测试部署或已安排的维护窗口进行。分别验证错误预期出口、上游断开、已有转发、新连接和恢复。Linux gate 的前两次瞬时失败会保留监听并接受新连接，第三次连续失败才关闭；确认的 mismatch 在探测完成后关闭。这不是“断开后立即拒绝一切请求”的保证。不要为测试某一个窗口而停止其他窗口共用的 gate、代理、sshd 或 app-server。

对代理配置层的 Codex，应观察它自己的失败或恢复结果；即使单次请求在 gate 关闭后失败，也不能证明所有协议都无法绕过。Windows 登录浏览器也必须单独验证，且Windows App 源码和构建已补齐，实际部署与验收见 [Windows 软件](windows.md)。

扩展自动更新后，应重新核对：实际运行版本、包装器设置是否仍被读取、启动参数契约、进程命名空间、代理变量和断链行为。磁盘中最新安装的版本与当前窗口正在运行的版本可能不同。

仓库中的历史工具 `tools/claude-vscode-local-only` 通过匹配压缩后的扩展源码片段隐藏远程会话并改写后端。它有备份和拒绝未知版本的逻辑，但匹配依赖具体版本。本次当前安装包未检测到该工具预期的后端补丁，仍有远程会话请求处理代码。不能把“工具文件存在”写成“当前插件已关闭所有远程会话请求”，也不要对新版本强行替换未知字符串。

## 8. 本次本机取证范围

检查日期：2026-10-16（UTC+8）。只读取相关设置、脚本、扩展配置声明和运行进程的代理变量，没有为编写本文重启服务或插件。

| 证据 | 本次结果 |
| --- | --- |
| Remote Machine settings | `http.proxy=17898`；Claude 进程包装器已配置；Claude HTTP(S) 代理变量已配置 |
| `server-env-setup` | 磁盘文件设置了 17898；观察到的运行 Extension Host 未包含这些代理变量 |
| 注册安装版本 | Claude Code 2.1.301；Codex 26.1007.21434 |
| 一个正在运行的 Codex 插件后端 | 二进制来自 26.930.61225，HTTP/HTTPS 代理变量指向 17898；与父 Extension Host 使用相同网络 namespace |
| 其他 Codex 后端 | 存在不同代理环境，未统一计入保护范围 |
| Claude 用户级后台 launcher 配置 | 未发现 `processWrapper` 或 `CLAUDE_CODE_PROCESS_WRAPPER` |
| 当前 Claude 远程会话源码补丁 | 未检测到历史工具预期的后端补丁 |

这些是该日快照，不是新环境安装后的验收结果。当前安装包声明和运行中的旧版包可能同时存在，需按当前窗口核验。复现时应记录自己的版本和检查时间，使用脱敏结果，不发布完整 settings、认证缓存、进程参数、环境转储或私有网络配置。
