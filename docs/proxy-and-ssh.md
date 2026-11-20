# 专用代理、参数取得与 SSH 反向转发

## 1. 先固定入口，再检查出口

通用规则代理可能对 IP 查询站、Cloudflare、Claude 网页和 Anthropic API 选择不同节点。只在 ipify 看到正确 IP，不能推出 API 请求也使用该出口。

本方案用 Windows 的专用 `127.0.0.1:7899` listener 将进入它的请求直接交给固定住宅节点。Linux gate 再对三个目的地抽样验证。原始入口、Linux gate 和 Windows 浏览器 guard 是不同组件：`7899` 可用不代表 `17898` 或 `17899` 已经实现和放行。

## 2. 合并自己的 Mihomo 配置

[示例片段](../examples/mihomo-claude.example.yaml) 只包含 listener 和出站节点示意，不能作为无需修改的独立配置运行。部署者需要在私人配置中填写：

| 字段 | 含义 | 常见误区 |
| --- | --- | --- |
| `listeners[].listen/port` | 本机专用入口，默认 loopback:7899 | 绑定 0.0.0.0 会扩大可访问范围 |
| `listeners[].proxy` | 直接指定住宅出站 | 留空后又按通用 rules 分流 |
| `proxies[].server/port/type` | 自己代理服务的连接参数 | 服务器 IP 不一定就是最终公网出口 IP |
| `username/password` | 代理服务认证 | 不应填进 AdsPower 本地守卫的认证栏或提交 Git |
| `dialer-proxy` | 可选，住宅代理连接所经过的传输节点/组 | 需要真实已存在的组；可直连住宅服务器时删掉此字段 |

链式连接是“本机 → 前置传输 → 住宅代理 → 目标”。前置节点不应在住宅代理故障后变成最终出口，不添加 DIRECT 或通用代理的失败回退。多个前置节点是否可切换，要以它们最终仍通过同一住宅出口为条件。

[Mihomo listener 文档](https://wiki.metacubex.one/en/config/inbound/listeners/)说明 `proxy` 可以直接指定出站；[dialer-proxy 文档](https://wiki.metacubex.one/en/config/proxies/dialer-proxy/)说明前置传输关系。示例不管理现有 TUN、DNS、订阅刷新、系统代理或其他应用的规则，不应覆盖整份现有配置。

Windows 上先用实际安装的核心检查**合并后的私人完整配置**：

```powershell
# 替换为自己的核心及完整配置路径，不是直接运行仓库片段。
& 'C:\path\to\mihomo.exe' -t -f 'C:\path\to\private-config.yaml'
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 7899 -State Listen
```

语法检查通过和监听存在仍不能证明网络可用。下面的三项请求才提供参数观测。

## 3. 在 Windows 取得三个独立观测

这些命令不带账号认证，只访问公开边缘/trace 接口。`--disable` 必须是 curl 的第一个选项，忽略个人 curlrc；`--noproxy ""` 避免环境中的绕过规则。每项显式使用专用 7899。

```powershell
# ① 公网 IP：应与自己约定的固定出口一致。
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:7899 --proto =https --connect-timeout 5 --max-time 15 https://api.ipify.org

# ② Cloudflare：取 ip 和 loc。这里的 colo 只作记录。
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:7899 --proto =https --connect-timeout 5 --max-time 15 https://www.cloudflare.com/cdn-cgi/trace

# ③ Anthropic API：取最终服务响应的 CF-Ray 后缀，不使用 --fail。
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:7899 --proto =https --connect-timeout 5 --max-time 15 --dump-header - --output NUL https://api.anthropic.com/
```

Windows PowerShell 5.1 的原生命令传参可能丢弃空字符串。这里使用 Windows 专用的停止解析标记 `--%` 保留 curl 所需的空参数；命令按静态单行使用，不在标记后加 PowerShell 变量、管道或续行。参见 [Microsoft 参数解析文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing?view=powershell-7.5#passing-arguments-that-contain-quote-characters)。

将结果填入自己的参数记录：

| renderer 参数 | 取得方式 | 判定 |
| --- | --- | --- |
| `--expected-ip` | ① 的结果，同时与自己的代理服务约定核对 | 不是未经核验就自动信任任意返回值 |
| `--country` | ② 的 `loc`，例如 `US` | ② 的 `ip` 必须与①一致 |
| `--anthropic-colo` | ③ 的 `CF-Ray: <标识>-LAX` 中最后的 `LAX` | 以 API 目标的 CF-Ray 为准 |

③ 可能先显示代理的 `200 Connection established`，再显示最终 API 的状态/响应头；应看最终服务的 CF-Ray。根路径返回 401/404 可以说明边缘可达，不说明订阅、登录或模型权限。没有 CF-Ray、TLS 失败或请求超时都不能写成完成。

`https://claude.ai/cdn-cgi/trace` 是另一目的地：可用于未来 Windows guard 的独立验收，但**不能替代 Linux gate 的 API POP 参数**。三个站点即使相同出口，也可能接入不同 POP。

## 4. 准备 SSH 信任与认证

在 Windows 的 SSH config 合并 [别名示例](../examples/ssh-config.example)，使用自己的主机、用户名、端口及密钥。先执行普通交互 `ssh claude-server`，通过可靠渠道核验服务端 host key；密码或密钥口令的初始化不由 `BatchMode=yes` 完成。

隧道需要服务端 sshd 允许对应的 TCP forwarding。若拒绝，查看实际服务器策略；不要为此把远端监听开放到公网，也不要关闭 host key 检查。密钥带口令时，需使用者已允许的认证方式，例如已解锁的 Windows ssh-agent。

## 5. 从 Windows 建立一条独立隧道

先确认原有 App/其他客户端没有维护同一 R:7899。一个监听只应有一个明确的维护者，避免同时启用手动隧道和另一个 supervisor。

```powershell
ssh -NT -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ControlMaster=no -o ControlPath=none -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -R 127.0.0.1:7899:127.0.0.1:7899 claude-server
```

远端含义是 `Linux loopback:7899 → SSH → Windows loopback:7899`。显式禁用复用现有 ControlMaster，便于明确这条隧道的进程所有权。命令保持前台运行，没有终端输出不等于异常；关闭终端后该手动维护路径就结束。

`ExitOnForwardFailure` 只能确认请求监听成功等 SSH 层错误，不能确认 Windows 7899 或住宅上游真实可用。ServerAlive 检查 SSH 连接状态，也不是应用层出口验证。

## 6. 在 Linux 逐项复验

以下在 Linux 宿主执行，依然使用**原始上游 7899**，不是 gate：

```bash
ss -lnt 'sport = :7899'
curl --disable --noproxy '' --proxy http://127.0.0.1:7899 --proto '=https' --connect-timeout 5 --max-time 15 https://api.ipify.org
curl --disable --noproxy '' --proxy http://127.0.0.1:7899 --proto '=https' --connect-timeout 5 --max-time 15 https://www.cloudflare.com/cdn-cgi/trace
curl --disable --noproxy '' --proxy http://127.0.0.1:7899 --proto '=https' --connect-timeout 5 --max-time 15 --dump-header - --output /dev/null https://api.anthropic.com/
```

结果应与预期 IP/国家/API POP 相符。通过后才进入 [Linux 渲染和安装](linux.md)。在 gate 安装之后，可以用 `claude-ip-guard check` 检查相同上游，`enforce` 再检查服务状态和近期结果。

## 7. 故障定位和维护

| 现象 | 有效证据 | 解释与处理方向 |
| --- | --- | --- |
| Windows 7899 不监听 | 核心进程和 listener 状态 | 先修复本机配置，不去修改 Linux gate |
| 普通 SSH 不通 | 目标/认证/host key/路由错误 | 先完成普通登录，不用转发测试代替 |
| SSH 报远端端口占用 | R 的 socket owner/cgroup/会话 | 识别维护者，避免新建重复隧道 |
| R:7899 监听但 CONNECT 超时 | W 的真实请求、R 的真实请求、所属 SSH 会话 | 可能是残留会话或上游不可用；监听存在不是健康证明 |
| IP/国家正确、API POP 不同 | API 最终 CF-Ray | 路由约束不满足，不代表一定发生 IP 泄漏；核验原因后整体更新私人参数 |
| 上游恢复而对话仍报错 | gate 状态与应用新请求 | gate、隧道、应用重试分别恢复，旧流不自动复活 |

处理残留隧道前，先记录 socket、cgroup、会话时间、登录来源和该会话是否承载工作负载；不要批量停止 sshd。故障注入只用于自己的空闲测试部署，不能拿共享活跃服务做断链试验。

通用/Git 代理可继续独立使用。不要为修复 GitHub 把 gate 唯一上游改回规则端口，也不要在整个 shell profile 中全局导出住宅代理。[Windows 连接管理器](windows.md)现已提供自动重连、托盘和自启源码。使用管理器时停用维护同一专用端口的旧任务；Codex 的普通 7897 隧道与 Claude 住宅链分别维护。
