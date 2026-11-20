# Linux Claude CLI / VS Code 防护部署

这一部分把 Claude 进程的公网通信限制到经过校验的专用代理：先确认固定 IPv4、Cloudflare 国家和 Anthropic 的 CF-Ray POP，再开放本地代理。Claude 子进程运行在独立网络 namespace 中，不能直接使用宿主网卡或宿主 DNS。仓库中的 Linux 文件是模板，必须先渲染；不包含任何人的登录态、代理密码、SSH 私钥或实际部署地址。

## 1. 流量经过哪里

```text
Claude CLI（ccen）或 VS Code Claude 子进程
  → claude-net-sandbox → systemd 用户 scope → bubblewrap 网络 namespace
  → namespace 内 127.0.0.1:17898
  → /run/claude-ip-gate/proxy.sock（从宿主只读挂载的 Unix socket）
  → 宿主 claude-ip-gate
  → 宿主 127.0.0.1:7899 专用代理 / SSH RemoteForward
  → 你自己配置并核验的固定出口
```

| 地址 / 文件 | 作用 |
| --- | --- |
| 宿主 `127.0.0.1:7899` | 上游专用住宅代理隧道，由 Windows 连接管理器或你自己的 SSH 连接维护 |
| 宿主 `127.0.0.1:17898` | gate 通过检查后才开放的 HTTP 代理入口 |
| 宿主 `/run/user/<UID>/claude-ip-gate/proxy.sock` | 用户私有的 gate Unix socket，权限 0600 |
| namespace 内 `127.0.0.1:17898` | 转发到 gate 的私有入口 |
| namespace 内 `127.0.0.1:7898` | 兼容旧工具命令的入口，同样转发到 gate；不是宿主 7898 |
| `/run/user/<UID>/claude-ip-gate/status` | 含 hostname、boot ID、daemon PID、最近检查结果的原子状态文件 |

Linux gate 当前**只选择上游 7899**，不回退到规则代理 7898。普通终端不需要导出全局代理；`ccen` 会拒绝已有 HTTP(S)/ALL_PROXY 的终端，避免意外继承不明确的路径。

## 2. 准备条件

- Linux、可用的 systemd **用户** manager：`systemctl --user` 能连接会话。
- Python **3.10+**、Bash 4.4+、curl、bubblewrap、util-linux 的 `flock`、coreutils、OpenSSH。可选 SSH relay 另需支持 `nc -U` 的 `netcat-openbsd`。
- 内核和系统策略允许 bubblewrap 创建 network/PID/IPC namespace，并支持此处的用户 systemd 沙箱选项。受限容器、关闭 user namespace 的机器需要管理员调整；不要通过跳过 sandbox 获得“通过”。
- Claude CLI 已通过官方方式安装在 `$HOME/.local/bin/claude`；不要把别人的 CLI 登录目录或认证文件复制过来。
- 你自己的专用代理已经在 Linux 的 `127.0.0.1:7899` 可用。Windows 管理器负责反向隧道时，先完成 Windows 端部署和 SSH 主机信任核验。
- 在个人 `LOCPATH=$HOME/.local/lib/locale` 下生成并验证 `en_SG.UTF-8`。所有入口都设置这个 LOCPATH，不能仅凭系统 `locale -a` 有同名条目就跳过验证。此套部署固定使用 `Asia/Singapore` 和该 locale，它们是运行环境设置，不能证明网络出口位置。

Debian/Ubuntu 的依赖示例（由你在目标机执行，渲染工具不会安装软件）：

```bash
sudo apt-get install python3 bubblewrap curl util-linux openssh-client netcat-openbsd locales
install -d -m 755 "$HOME/.local/lib/locale"
localedef --no-archive -i en_SG -f UTF-8 "$HOME/.local/lib/locale/en_SG.UTF-8"
LOCPATH="$HOME/.local/lib/locale" LC_ALL=en_SG.UTF-8 python3 -c 'import locale,sys; print(locale.setlocale(locale.LC_ALL, "en_SG.UTF-8")); sys.exit(0 if locale.nl_langinfo(locale.CODESET) == "UTF-8" else "locale is not UTF-8")'
systemctl --user is-system-running
```

`localedef` 需要系统提供 locale 源文件。上面的 Python 检查必须成功并输出 `en_SG.UTF-8`；检查不能只看目录存在，也不能把 locale warning 当成通过。需要退出 SSH 后继续运行服务时，管理员可为**你自己的账户**启用 linger：`loginctl enable-linger <login-name>`。按机器管理规范处理，不要修改其他人的账户。

## 3. 渲染到独立 staging 目录

在仓库根目录运行。固定 IP、国家、POP 必须来自你自己核验过的链路，不能照搬截图或其他人的数值。

```bash
read -r -p '你的固定出口 IPv4: ' CCEN_EXPECTED_IP
read -r -p 'Cloudflare 国家代码，例如 US: ' CCEN_COUNTRY
read -r -p 'Anthropic CF-Ray POP，例如 LAX: ' CCEN_ANTHROPIC_COLO
CCEN_TARGET_HOME="$(readlink -f "$HOME")"
CCEN_STAGE="$(mktemp -d /tmp/ccen-stage.XXXXXX)/rendered"
python3 tools/render-linux.py \
  --home "$CCEN_TARGET_HOME" --uid "$(id -u)" \
  --expected-ip "$CCEN_EXPECTED_IP" \
  --country "$CCEN_COUNTRY" --anthropic-colo "$CCEN_ANTHROPIC_COLO" \
  --output "$CCEN_STAGE"
```

`--home` 是目标 Linux 用户的规范化绝对 HOME；上例用 `readlink -f` 解析 HOME 别名。`--uid` 是目标用户的非 root UID；交叉准备时填目标用户的值。为保证 Bash、Python、JSON、systemd 四种语法中的替换都为字面量，目前路径只支持字母、数字、`_ . / -`，不支持空格、引号、反斜杠或 shell 变量文本。请传入展开后的绝对路径，不要写字面的 `$HOME`。

渲染器只读取仓库里列明的代码和 unit，不读取 `~/.ssh`、`~/.claude` 或私有 `.env`。输出目录必须不存在；它拒绝覆盖现有 staging，也拒绝输出到目标 HOME 的 `.local/.config/.ssh/bin` 或 `/run/user`。它先检查完整 token 替换、Bash/Python/JSON 语法，然后输出：

```text
rendered/
  bin/                         核心启动入口
  libexec/                     gate、sandbox launcher、PID1 relay
  systemd/                     默认仅 claude-ip-gate.service
  config/vscode-machine-settings.json
  optional/host-runner/        单独存放，默认不安装、不启用
  render-manifest.json         参数、文件 SHA256、required_directories、install_files
```

默认不包含实验室 SSH relay，启动 Claude 不要求任何 `fpga*` 主机。渲染器不启动 Claude、不探测公网、不安装文件、不调用 systemd。未渲染的入口会拒绝运行；代码模板不能直接复制进个人 `bin`。

## 4. 审阅、核验和安装核心组件

### 4.1 固定文件清单与空目录

核心安装只有以下 **7 个文件**。manifest 的 `install_files` 同时给出来源、目标、权限和 component；不要对仓库根目录或整个 HOME 执行递归复制。

| staging 来源 | 目标（相对目标 HOME） | 权限 |
| --- | --- | --- |
| `bin/ccen` | `.local/bin/ccen` | 0755 |
| `bin/claude-ip-guard` | `.local/bin/claude-ip-guard` | 0755 |
| `bin/claude-net-sandbox` | `.local/bin/claude-net-sandbox` | 0755 |
| `libexec/claude-ip-gate` | `.local/libexec/claude-ip-gate` | 0755 |
| `libexec/claude-net-launcher` | `.local/libexec/claude-net-launcher` | 0755 |
| `libexec/claude-net-pid1.py` | `.local/libexec/claude-net-pid1.py` | 0755 |
| `systemd/claude-ip-gate.service` | `.config/systemd/user/claude-ip-gate.service` | 0644 |

CLI 自身的 `.local/bin/claude` **不在覆盖清单内**。wrapper 支持该路径的有效可执行符号链接，包括原生安装使用的版本链接。先检查 `test -x "$HOME/.local/bin/claude"` 和 `readlink -f "$HOME/.local/bin/claude"`；CLI 缺失时由使用者安装，不能复制其他人的登录目录。

即使尚未安装 host-runner 或 VS Code，也要创建下面 7 个目录。三个 systemd 控制目录必须预先存在，空目录也有作用：launcher 将它们只读绑定，避免进程树通过创建新的用户 unit 改变原有控制。缺少时明确拒绝启动，不在运行时静默创建。

| 相对目标 HOME 的目录 | 权限 | 用途 |
| --- | --- | --- |
| `.local/bin` | 0755 | 三个公开入口 |
| `.local/libexec` | 0755 | 私有实现，整体只读绑定 |
| `.local/lib/locale` | 0755 | 已按第 2 节生成的个人 locale |
| `.config/ccen` | 0700 | 必需的私有控制目录，核心部署可为空 |
| `.config/systemd/user` | 0700 | 常规用户 units |
| `.config/systemd/user.control` | 0700 | systemd 用户持久控制配置，可为空 |
| `.local/share/systemd/user` | 0700 | 另一用户 unit 搜索路径，可为空 |

为保证绑定保护准确，控制路径及其祖先目录不支持符号链接，包括 `.local/bin`、`.local/libexec`、私有配置文件、host-runner 状态路径、systemd 目录和已有的 VS Code server 目录/设置。遇到这种布局应先核实其真实路径并调整部署，不能删除链接来“试试看”。这个约束不包括 Claude 本体的版本符号链接。VS Code server 或 insiders 根目录不存在时不会创建；存在时只读挂载，因此从 Claude 进程树内部更新扩展会失败，需要在普通宿主侧操作。

### 4.2 安装前核验 staging 与目标

以下只读核验确认 staging 哈希、渲染参数与当前目标账户一致，以及核心目录没有符号链接祖先。跨用户准备 staging 后，应由目标用户在目标机执行安装；不要使用 sudo 把个人文件安装成 root 所有。

```bash
python3 - "$CCEN_STAGE" "$CCEN_TARGET_HOME" "$(id -u)" <<'CCEN_VERIFY_PY'
import hashlib, json, pathlib, sys
def require(condition, message):
    if not condition:
        raise SystemExit(message)
stage = pathlib.Path(sys.argv[1])
manifest = json.loads((stage / "render-manifest.json").read_text())
require(manifest["home"] == sys.argv[2], "目标 HOME 不匹配")
require(manifest["uid"] == int(sys.argv[3]), "目标 UID 不匹配")
for name, record in manifest["files"].items():
    source = stage / name
    require(not source.is_symlink(), f"staging 文件为链接: {name}")
    require(hashlib.sha256(source.read_bytes()).hexdigest() == record["sha256"], f"哈希错误: {name}")
control_paths = [entry["path"] for entry in manifest["required_directories"]]
control_paths += [manifest["home"] + "/.local/state/ccen"]
for entry in manifest["install_files"]:
    if entry["installed_by_default"]:
        target = pathlib.Path(entry["destination"])
        require(not target.is_symlink(), f"控制文件为链接: {target}")
        require(not target.exists() or target.is_file(), f"文件位置被目录占用: {target}")
        control_paths.append(str(target.parent))
for name in control_paths:
    path = pathlib.Path(name)
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), f"控制路径含链接: {ancestor}")
    require(not path.exists() or path.is_dir(), f"目录位置被文件占用: {path}")
print("staging 哈希、目标账户、目录布局核验通过")
CCEN_VERIFY_PY
```

核验失败时停止安装并处理原因。`required_directories` 用于核对空目录，不表示 renderer 已在 HOME 创建这些目录。哈希绑定的是这次渲染的内容，不是对恶意仓库或已被篡改 manifest 的独立信任证明；先核验仓库来源与提交。

### 4.3 备份和安装

下面数组定义用于后面的回滚和卸载；重新打开 shell 时先重新定义数组、`CCEN_TARGET_HOME` 和所选 staging。已有部署先备份同名控制脚本和 unit；另外单独备份自己的 VS Code Machine 设置，本文不自动修改它。

```bash
set -euo pipefail
: "${CCEN_TARGET_HOME:?先完成第 3 节并核对目标 HOME}"
: "${CCEN_STAGE:?先完成第 3 节并核对 staging}"
CCEN_CORE_BIN=(ccen claude-ip-guard claude-net-sandbox)
CCEN_CORE_LIBEXEC=(claude-ip-gate claude-net-launcher claude-net-pid1.py)
CCEN_BACKUP="$CCEN_TARGET_HOME/.local/state/ccen/backups/$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$CCEN_BACKUP/bin" "$CCEN_BACKUP/libexec" "$CCEN_BACKUP/systemd"
for CCEN_FILE in "${CCEN_CORE_BIN[@]}"; do
  if [[ -e "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE" ]]; then
    cp -p -- "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE" "$CCEN_BACKUP/bin/"
  fi
done
for CCEN_FILE in "${CCEN_CORE_LIBEXEC[@]}"; do
  if [[ -e "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE" ]]; then
    cp -p -- "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE" "$CCEN_BACKUP/libexec/"
  fi
done
if [[ -f "$CCEN_TARGET_HOME/.config/systemd/user/claude-ip-gate.service" ]]; then
  cp -p -- "$CCEN_TARGET_HOME/.config/systemd/user/claude-ip-gate.service" "$CCEN_BACKUP/systemd/"
fi
if [[ -f "$CCEN_TARGET_HOME/.local/state/ccen/deployment-manifest.json" ]]; then
  cp -p -- "$CCEN_TARGET_HOME/.local/state/ccen/deployment-manifest.json" "$CCEN_BACKUP/"
fi
install -d -m 755 "$CCEN_TARGET_HOME/.local/bin" "$CCEN_TARGET_HOME/.local/libexec" "$CCEN_TARGET_HOME/.local/lib/locale"
install -d -m 700 "$CCEN_TARGET_HOME/.config/ccen" \
  "$CCEN_TARGET_HOME/.config/systemd/user" "$CCEN_TARGET_HOME/.config/systemd/user.control" \
  "$CCEN_TARGET_HOME/.local/share/systemd/user"
for CCEN_FILE in "${CCEN_CORE_BIN[@]}"; do
  install -m 755 "$CCEN_STAGE/bin/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE"
done
for CCEN_FILE in "${CCEN_CORE_LIBEXEC[@]}"; do
  install -m 755 "$CCEN_STAGE/libexec/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE"
done
install -m 644 "$CCEN_STAGE/systemd/claude-ip-gate.service" "$CCEN_TARGET_HOME/.config/systemd/user/claude-ip-gate.service"
install -m 600 "$CCEN_STAGE/render-manifest.json" "$CCEN_TARGET_HOME/.local/state/ccen/deployment-manifest.json"
systemctl --user daemon-reload
systemctl --user enable --now claude-ip-gate.service
```

备份目录和 deployment manifest 属于个人部署记录，不应提交到仓库。上述命令不会安装 lab 文件或 `optional/host-runner`。有旧的 `~/bin/ccen` 时，PATH 可能继续命中它；先用 `command -v ccen` 核对，或明确运行 `$CCEN_TARGET_HOME/.local/bin/ccen`。

对运行中的旧 gate，`enable --now` 不会载入新的 Python 代码。升级需要在适当窗口执行 `systemctl --user restart claude-ip-gate.service`，这会切断 gate 转发；已运行的 sandbox 也不会自动替换 launcher，要退出后重新启动。参见第 10 节的升级/回滚顺序。

### 4.4 运行状态、配置来源与输出约定

期望值写在渲染后的脚本中，没有加载 `ccen.env` 的功能。gate unit 明确设置 HOME、XDG_RUNTIME_DIR、XDG_STATE_HOME、LOCPATH 和 locale，不依赖交互 shell 的环境。gate/guard 虽有 `CLAUDE_GUARD_EXPECTED_*` 环境覆盖，CLI 自身仍有固定检查，建议修改参数后重新渲染整套部署。

| 命令 | 是否联网 / 改变运行状态 | 正常输出 |
| --- | --- | --- |
| `claude-ip-guard status` | 只读状态，不做新探测 | stdout 状态字段；成功退出不代表放行 |
| `claude-ip-guard check` | 经上游执行一次真实探测；不创建监听、不刷新 daemon 状态 | 成功 stdout `[OK]`；失败 stderr `[BLOCKED]` |
| `claude-ip-guard enforce` | 可能启动 unit，请求刷新或复用新鲜结果 | 成功 stdout `[OK]`；失败 stderr，非零退出 |
| `claude-net-sandbox <绝对可执行路径> ...` | 强制 gate 验收后启动隔离进程树 | stdout 留给子进程；guard stdout 被抑制，诊断走 stderr |
| `ccen` | 交互检查、会话选择与启动 | stdout 含检查菜单，不是 stdio JSON 入口 |

```bash
"$CCEN_TARGET_HOME/.local/bin/claude-ip-guard" status
"$CCEN_TARGET_HOME/.local/bin/claude-ip-guard" check
"$CCEN_TARGET_HOME/.local/bin/claude-ip-guard" enforce
journalctl --user -u claude-ip-gate.service -n 50 --no-pager
```

`active/running` 只说明 daemon 在运行；还要看 `status=allowed`、`reason=all checks passed`、正确上游/出口身份和最近时间。`enforce` 最多等 guard 锁 45 秒，再等刷新约 30 秒，不能按单个 curl 超时估计启动延迟。不要通过关闭 wrapper、改成直连或添加其他代理来让检查“通过”。

## 5. CLI 与 VS Code 分别接入

CLI 在普通终端运行 `ccen`，通过检查后可选 Resume/New；传入 Claude 参数时会要求交互确认。例如 `ccen --resume`。它不是为无人值守批处理设计的入口。直接运行原始 `claude` 不会自动使用这里的 sandbox，日常必须使用 `ccen` 或配置好的 wrapper。

VS Code Remote SSH 中，将 staging 的 `config/vscode-machine-settings.json` **合并**到远端 Machine 设置中，保留你自己的其他设置；不要直接覆盖整份文件。关键设置如下：

```json
{
  "http.proxy": "http://127.0.0.1:17898",
  "http.proxySupport": "override",
  "http.proxyStrictSSL": true,
  "http.useLocalProxyConfiguration": false,
  "http.noProxy": ["localhost", "127.0.0.1", "::1"],
  "claudeCode.claudeProcessWrapper": "/home/your-user/.local/bin/claude-net-sandbox",
  "claudeCode.useTerminal": false
}
```

生成的完整片段还包括 Claude 子进程的 HTTP(S)_PROXY、loopback NO_PROXY 和两个非必要流量设置。wrapper 会设置完整 locale，并保留 VS Code 扩展需要的 stdio 协议。`http.proxy` 也会影响支持该设置的远端扩展请求；只有 Claude wrapper 启动的进程树才有此处的 network namespace。它不会自动隔离 Codex 扩展或所有 VS Code 插件。

必须在设置 UI 核对**最终生效值**为 `claudeCode.useTerminal=false`，使用扩展 GUI 模式；某些版本的 terminal 模式直接运行原始 Claude，可能绕过 wrapper。用户、远端、工作区和项目设置可能相互覆盖，复制片段本身不是生效证据。不要关闭 `http.proxyStrictSSL`；需要私有 CA 时，由管理员安装经核验的 CA，并按 VS Code/Node 的受信证书机制配置。

更改设置后重新加载窗口，并从 Claude 扩展发起实际请求验证。不同扩展版本对 wrapper 的支持需要现场确认。仓库的 `tools/claude-vscode-local-only` 是旧版 Claude 扩展的精确 JavaScript 补丁，用于关闭远程会话列表；它与 IP gate 独立，版本不匹配会拒绝修改，默认部署不执行这个补丁。

## 6. 放行规则、故障行为与验收

每轮并行进行三项 HTTPS 检查，全都使用明确指定的 `127.0.0.1:7899` 代理，禁止 curlrc 和 NO_PROXY 绕行：

1. ipify 返回配置的固定 IPv4。
2. Cloudflare trace 返回同一 IPv4 和配置的国家；trace 的 `colo` 只记录，不要求固定。
3. Anthropic 根路径可返回 HTTP 响应且带 CF-Ray，CF-Ray 的 POP 后缀与配置一致。

Anthropic 的 401/404 等状态可以满足这项**网络边缘**检查，不能证明登录、订阅、模型权限或 Claude 成功回复。Cloudflare POP 也不是住宅属性证明。gate 与 guard 检查 API POP；CLI 启动依赖 guard 的完整结果，随后额外的 API curl 只复核非 000 HTTP 响应，不单独提取 CF-Ray。因此 CLI 的单条“HTTP 可达”日志不能作为独立 POP 验收。

健康时每 45 秒开始下一轮检查；失败后约每 10 秒复查。完成探测后发现身份/位置 `mismatch` 会关闭监听并切断现有转发。非 mismatch 的超时等瞬时失败，**前两次保留监听、现有连接，也接受新连接**；第三次连续失败才关闭。一次成功会清零计数。状态中的 `allowed` 必须结合 `reason` 判断是否 degraded；guard 不接受 degraded 结果作为新的启动验收。

这是一套周期采样和容错策略，不能保证出口变化瞬间零字节流出。按检查间隔与三次探测的等待预算粗算，超时场景可能超过 60 秒，约 75–84 秒量级；这是源码参数推算，不是实测时延或硬上限，调度异常还会增加时间。新启动时可复用同一 daemon、同一 boot、同一主机在 10 秒内的成功结果。

建议按以下证据逐层验收，故障注入只在自己的空闲测试环境进行：

| 验收项 | 应得到的证据 |
| --- | --- |
| 配置完整 | renderer 成功、manifest 参数正确、模板 token 均已替换 |
| 上游与 gate | `check` 三项成功、`status` 的 hostname/boot/PID 正确且监听 active |
| sandbox | 按 [验证流程](verification.md) 的完整 here-doc 核验 namespace、网卡、直连失败与显式 HTTPS 代理出口 |
| Claude CLI | 从 `ccen` 实际发送消息并获得回复 |
| VS Code Claude | 从扩展实际发送消息并获得回复，子进程位于 `claude-net-<UID>-*.scope` |
| 故障注入 | 停止自己测试隧道时最终关闭监听；配置错误的固定 IP 时不开放；恢复正确链路后自动恢复 |

不要在正在承载他人会话的 gate、代理或 SSH 会话上做断网测试。本文记录的是实现规则；新机器必须自己完成验收，仓库测试不替代现场网络、任务或账号测试。

## 7. 可选实验室 SSH relay

普通部署环境跳过本节。relay 是为了让私有 namespace 中的工具访问明确允许的 SSH 主机，默认没有这些通道。模板保留 `fpga01/02/03/04/05/06` 作为功能标签，你必须提供自己的目标映射；仓库没有实际实验室地址或密钥。

启用时在第 3 节的渲染命令上增加全部参数：

```bash
  --enable-lab-relays \
  --lab-hostname lab-host.example \
  --ssh-user student \
  --ssh-identity /home/student/.ssh/id_ed25519_lab \
  --ssh-known-hosts /home/student/.ssh/known_hosts \
  --lab-target fpga01=192.0.2.11 \
  --lab-target fpga02=192.0.2.12 \
  --lab-target fpga03=192.0.2.13 \
  --lab-target fpga05=192.0.2.15 \
  --lab-target fpga06=192.0.2.16
```

上面是追加参数片段；`192.0.2.0/24` 是文档地址，必须换成你的实际可达目标。`--lab-hostname` 必须与安装 relay 的本机 hostname 条件匹配。`fpga04` 表示本机 sshd `127.0.0.1:22`，其余映射到指定主机的 22 端口。AD 登录名可用 `--ssh-user 'DOMAIN\student'`；用户名允许字母、数字、`_ . @ -` 和反斜杠，渲染到 Bash 单引号 SSH option 中，保留字面值。

你自己生成 SSH key、核验每台主机 hostkey 后准备 known_hosts。helper 使用 `HostKeyAlias=fpgaXX`，所以 known_hosts 要有对应别名的可信记录；单独运行 `ssh-keyscan` 没有完成身份核验。渲染器只记路径，从不读取或生成 key。helper 禁用 agent forwarding，使用明确 identity、严格 hostkey、固定目标 Unix relay；Unix peer UID 必须匹配。

lab 的文件与核心清单分开安装；不会覆盖 Claude CLI。使用完整映射重新渲染到新 staging 后，检查 manifest 中 `component=lab` 的文件。下面清单明确安装 7 个 helper、3 个 relay 实现和 3 个 unit；基础 relay 两个，另一个 unit 模板生成 4 个实例。

```bash
CCEN_LAB_BIN=(claude-ssh-fpga01 claude-ssh-fpga02 claude-ssh-fpga03 claude-ssh-fpga04 claude-ssh-fpga05 claude-ssh-fpga06 claude-ssh-lab)
CCEN_LAB_LIBEXEC=(claude-fpga03-ssh-relay claude-fpga04-ssh-relay claude-lab-ssh-relay)
CCEN_LAB_UNITS=(claude-fpga03-ssh-relay.service claude-fpga04-ssh-relay.service claude-lab-ssh-relay@.service)
for CCEN_FILE in "${CCEN_LAB_BIN[@]}"; do
  install -m 755 "$CCEN_STAGE/bin/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE"
done
for CCEN_FILE in "${CCEN_LAB_LIBEXEC[@]}"; do
  install -m 755 "$CCEN_STAGE/libexec/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE"
done
for CCEN_FILE in "${CCEN_LAB_UNITS[@]}"; do
  install -m 644 "$CCEN_STAGE/systemd/$CCEN_FILE" "$CCEN_TARGET_HOME/.config/systemd/user/$CCEN_FILE"
done
systemctl --user daemon-reload
systemctl --user enable --now claude-fpga03-ssh-relay.service claude-fpga04-ssh-relay.service
systemctl --user enable --now \
  claude-lab-ssh-relay@fpga01.service claude-lab-ssh-relay@fpga02.service \
  claude-lab-ssh-relay@fpga05.service claude-lab-ssh-relay@fpga06.service
```

还要按第 4 节安装同一次 lab 渲染出的核心文件：其中 launcher 的 lab 开关已开启。先启动并核验 relay，再重新启动 Claude；lab launcher 要求 fpga03 和本机两个基础 socket 可用。其他 helper 优先使用独立 socket；没有时可经本机 sshd 的 `ssh -W` 转发。该模式授予 SSH 登录后的宿主执行能力：目标账户可执行宿主命令，互联网命令也可能在宿主执行。此通道是**可信管理能力**，不属于 gate 的公网隔离保证，不应向不可信 agent 或不可信脚本开放。

## 8. 可选 host-runner：默认关闭

`optional/host-runner` 是批准的离线宿主任务 broker，不属于默认核心安装。renderer 总是将其单独存放，不会把 socket unit 放入默认 systemd 目录；也没有自动启动或“批准任意命令”。

需要它时由宿主管理者先审阅 policy：固定 profile 名、绝对 command/cwd、超时、允许环境和可选 SHA256。客户端只能提交 profile 名与 request ID。示例 policy 仅有取消、退出码、持久性测试，不包含实际实验任务。完整安装清单只有 6 个文件，位于 manifest 的 `component=host-runner`：

```bash
set -euo pipefail
: "${CCEN_TARGET_HOME:?先完成第 3 节}"
: "${CCEN_STAGE:?先完成第 3 节}"
install -d -m 700 "$CCEN_TARGET_HOME/.local/state/ccen/host-jobs"
install -m 755 "$CCEN_STAGE/optional/host-runner/bin/ccen-host-run" "$CCEN_TARGET_HOME/.local/bin/ccen-host-run"
for CCEN_FILE in ccen-host-runner ccen-host-job; do
  install -m 755 "$CCEN_STAGE/optional/host-runner/libexec/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE"
done
for CCEN_FILE in ccen-host-runner.service ccen-host-runner.socket; do
  install -m 644 "$CCEN_STAGE/optional/host-runner/systemd/$CCEN_FILE" "$CCEN_TARGET_HOME/.config/systemd/user/$CCEN_FILE"
done
install -m 600 "$CCEN_STAGE/optional/host-runner/config/host-runner.json" "$CCEN_TARGET_HOME/.config/ccen/host-runner.json"
systemctl --user daemon-reload
systemctl --user enable --now ccen-host-runner.socket
```

broker 按 Unix peer UID 校验，任务通过用户 systemd transient service 管理完整进程组；用清空后的环境和 `RestrictAddressFamilies=AF_NETLINK` 禁止普通联网 socket，同时保留宿主设备视图支持 CUDA/FPGA。需要现场验证系统过滤是否生效。profile 的解释器可执行文件必须 root 拥有且不可被组/其他用户写；脚本、模型、环境与可写依赖仍需你审计，哈希映射也需要覆盖实际关键文件。

`ccen-host-run submit <profile>`、`status <job-id>`、`logs <job-id>`、`wait <job-id>`、`cancel <job-id>` 提供管理接口。关闭时 `systemctl --user disable --now ccen-host-runner.socket ccen-host-runner.service`。不启用它不会影响核心 Claude 网络防护。

## 9. 保护范围与升级

- bwrap 的根文件系统主要保持可写；只读绑定控制代码、systemd 用户目录、VS Code server 和 cgroup，并屏蔽私有配置、DBus、host-job 状态。它不是完整的数据访问隔离或恶意代码安全边界。
- `/run` 和 `/tmp` 被替换为私有空视图。从宿主 `/tmp` 或 `/run` 中的项目启动会使工作目录在 sandbox 内不可见；把项目放在持久工作目录后启动。宿主 `/run/user/<UID>` 中的其他 Unix socket 不会原样暴露，依赖这些 socket 的工具需要单独评估。私有 namespace 里能创建普通 TCP socket；保护的是到宿主/外网的路由，而非禁止 socket 构造本身。
- 所有普通公网目的地共享同一代理，不是 Claude 域名 allowlist。gate 用三个目的地抽样验证链路；上游若按域名分流，抽样通过不等于所有目的地都有同一出口，因此必须使用专用固定出口通道。
- gate TCP 只监听 loopback，但同宿主其他本地用户仍可能使用该 TCP 入口；Unix socket 为用户私有。不要把监听地址改成 `0.0.0.0`。
- 保护依赖从 wrapper 启动、内核隔离有效、可信宿主与配置；不会自动约束其他进程、宿主 SSH 命令、Codex 全部插件或浏览器。Windows/AdsPower 与 Codex 扩展必须按相应文档独立配置并核验。
- 更新 Claude/VS Code/bubblewrap/systemd 后，重新验证 wrapper 接口、namespace 直连失败和真实请求；旧版 JavaScript 补丁可能不再适用。
- 停用核心 gate：`systemctl --user disable --now claude-ip-gate.service`，现有转发会断开。卸载前先还原自己的 VS Code proxy/wrapper 设置；不要留下扩展指向不存在的脚本，也不要让原始 Claude 因而意外直连。

## 10. 升级与回滚

一次升级的验收单位是同一份 manifest 绑定的 CLI、guard、gate、sandbox、launcher、PID1 和 unit，不是单独更新某个文件。

1. 记录当前源码提交、部署 manifest、`claude-ip-guard status` 和 `systemctl --user show claude-ip-gate.service --property=MainPID,ExecMainStartTimestamp,UnitFileState`，确认哪些自己的会话正在使用 gate。
2. 渲染到全新的 staging，执行第 4.2 节核验，备份第 4.3 节的 7 个核心文件、旧 manifest、自己的 VS Code 设置。有 lab 或 broker 时按其明确清单另行备份；不要把认证目录放入备份包。
3. 通知这个用户账户下受影响的使用者，正常退出自己的 Claude 会话和任务。在维护窗口停止自己的 gate：`systemctl --user stop claude-ip-gate.service`。这是有中断的维护动作；不要停他人的代理或 SSH 工作。
4. 按第 4.3 节安装，daemon-reload 并启动 gate。先检查真实网络路径，再按 [验证流程](verification.md) 分别验收 sandbox、CLI、扩展 GUI。已运行的旧 sandbox 不会自动切换版本；必须重新启动会话。
5. 如果升级失败，保持 Claude 停止。使用备份的旧脚本与旧 unit 恢复，daemon-reload 后再启动原 gate；若修改过编辑器设置，恢复对应备份。重新验收后才继续原会话。

核心回滚的精确命令如下；`CCEN_BACKUP` 必须指向你已核验的那次备份。只有 7 个旧核心文件都存在时使用；首次安装的空备份不能作为完整回滚包。

```bash
set -euo pipefail
: "${CCEN_TARGET_HOME:?设置并核验目标 HOME}"
: "${CCEN_BACKUP:?设置并核验旧版本备份目录}"
CCEN_CORE_BIN=(ccen claude-ip-guard claude-net-sandbox)
CCEN_CORE_LIBEXEC=(claude-ip-gate claude-net-launcher claude-net-pid1.py)
for CCEN_FILE in "${CCEN_CORE_BIN[@]}"; do test -f "$CCEN_BACKUP/bin/$CCEN_FILE"; done
for CCEN_FILE in "${CCEN_CORE_LIBEXEC[@]}"; do test -f "$CCEN_BACKUP/libexec/$CCEN_FILE"; done
test -f "$CCEN_BACKUP/systemd/claude-ip-gate.service"
systemctl --user stop claude-ip-gate.service
for CCEN_FILE in "${CCEN_CORE_BIN[@]}"; do
  install -m 755 "$CCEN_BACKUP/bin/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE"
done
for CCEN_FILE in "${CCEN_CORE_LIBEXEC[@]}"; do
  install -m 755 "$CCEN_BACKUP/libexec/$CCEN_FILE" "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE"
done
install -m 644 "$CCEN_BACKUP/systemd/claude-ip-gate.service" "$CCEN_TARGET_HOME/.config/systemd/user/claude-ip-gate.service"
if [[ -f "$CCEN_BACKUP/deployment-manifest.json" ]]; then
  install -m 600 "$CCEN_BACKUP/deployment-manifest.json" "$CCEN_TARGET_HOME/.local/state/ccen/deployment-manifest.json"
fi
systemctl --user daemon-reload
systemctl --user start claude-ip-gate.service
```

lab 代码更新需要在同一维护窗口重启两个基础 relay 和已启用的 4 个实例，SSH 管理连接会断开。关闭 lab 模式时先渲染默认模式、替换 launcher 并退出所有旧 lab sandbox，再停止这些 units；仅删除 helper 不会关闭已挂载的 socket。broker 的任务是单独 transient service，停止 broker 不会自动等价于取消所有已经提交的任务；先逐个确认 job ID 和日志，再决定取消或等待完成。

## 11. 卸载与保留的数据

先正常关闭自己的 Claude 会话，并从 VS Code 最终生效设置中恢复/移除本文添加的 proxy、wrapper、GUI 模式和环境变量项。不要直接恢复整份老 settings 文件而覆盖后来新增的无关设置；保留 TLS 校验。若需要继续使用 Claude，应先决定后续的网络接入方式，避免删除 wrapper 后无意直连。

只卸载默认核心时，精确删除下面 7 个控制文件。这里不删除官方 Claude、本人的登录态、SSH key、known_hosts、代理配置、locale、工作区、共享目录或备份。

```bash
set -euo pipefail
: "${CCEN_TARGET_HOME:?设置并核验目标 HOME}"
systemctl --user disable --now claude-ip-gate.service
for CCEN_FILE in ccen claude-ip-guard claude-net-sandbox; do
  rm -f -- "$CCEN_TARGET_HOME/.local/bin/$CCEN_FILE"
done
for CCEN_FILE in claude-ip-gate claude-net-launcher claude-net-pid1.py; do
  rm -f -- "$CCEN_TARGET_HOME/.local/libexec/$CCEN_FILE"
done
rm -f -- "$CCEN_TARGET_HOME/.config/systemd/user/claude-ip-gate.service"
systemctl --user daemon-reload
```

若启用了 lab，关闭顺序是先退出 lab sandbox，再停止 4 个实例与两个基础 unit。随后按第 7 节的 `CCEN_LAB_BIN`、`CCEN_LAB_LIBEXEC`、`CCEN_LAB_UNITS` 明确清单删除各自文件，不使用 `claude-*` 通配符删除。若启用了 broker，先处理自己的在途 job，关闭 socket/service，然后删除 `.local/bin/ccen-host-run`、`.local/libexec/ccen-host-runner`、`.local/libexec/ccen-host-job`、两个 `ccen-host-runner` units 和已确认不再需要的 `host-runner.json`。

```bash
systemctl --user disable --now \
  claude-lab-ssh-relay@fpga01.service claude-lab-ssh-relay@fpga02.service \
  claude-lab-ssh-relay@fpga05.service claude-lab-ssh-relay@fpga06.service \
  claude-fpga03-ssh-relay.service claude-fpga04-ssh-relay.service
systemctl --user disable --now ccen-host-runner.socket ccen-host-runner.service
```

上面两个停用命令仅供实际安装了对应组件时使用；不适用时跳过。保留 `.local/state/ccen` 下的备份、manifest、job 结果用于追溯，需要清理时由使用者单独决定。不要递归删除 `.local/bin`、`.local/libexec`、`.config/systemd/user` 或 `.config/ccen`，这些目录可能还有其他工具的内容。

## 12. 故障定位与离线回归边界

| 现象 | 优先检查 | 不应得出的结论 |
| --- | --- | --- |
| `systemctl --user` 无法连接 bus | 当前登录会话、runtime 目录、用户 manager、linger 策略 | 不要改用系统级 root service 掩盖问题 |
| `active/running` 但 gate 未放行 | status 的 reason、出口 IP/国家/Anthropic POP、7899 隧道 | daemon 活着不等于验证成功 |
| wrapper 报缺目录 | 第 4.1 节三个 systemd 目录和 `.config/ccen` 的存在、所有权 | 空目录不是可以省略的安装步骤 |
| wrapper 报 control path symlink | 命名路径及所有祖先的实际解析；与 CLI 本体版本链接区分 | 不要绕过校验或盲目删除链接 |
| `bwrap` 报 Operation not permitted | 内核/user namespace/bwrap 系统策略 | renderer 的语法通过不证明内核能力 |
| `bwrap` 找不到 cwd | 项目是否位于被替换的 `/tmp` 或 `/run` | 不代表原项目被删除 |
| locale warning / unsupported locale | 个人 LOCPATH 下的实际 `setlocale` 检查 | 目录存在或系统 locale 列表不足以证明可用 |
| CLI 可用而扩展失败 | 扩展版本、最终生效 `useTerminal=false`、wrapper 绝对路径、scope、真实请求 | 复制 settings 不是启动路径证据 |
| Anthropic 根路径 401/404 | 结合 CF-Ray/POP 看网络可达性，再单独验登录与真实模型请求 | HTTP 非零不等于账号或模型可用 |

离线回归命令：`python3 -m unittest discover -s tests -p test_render_linux.py -v`。测试在临时目录渲染，并使用假的 bwrap/systemd/curl 测试替身核验调用参数；覆盖必需空目录、CLI 版本符号链接、保护路径链接拒绝、argv 字面量、stdout/stderr/退出码、代理认证信息不输出、GUI/TLS 设置、token 和哈希。替身测试不证明实际内核隔离、systemd 功能或真实出口；这些仍需按 [验证流程](verification.md) 现场验收。
