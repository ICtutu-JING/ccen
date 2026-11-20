# 分层验收、失败路径与故障定位

## 1. 先确定验收对象

每份结果绑定一台设备、一份配置、一个入口和一个时间。运行“某个 curl 成功”不能同时验收浏览器、CLI、图形插件和所有 Codex 后端；维护者设备与 CI 的结果也不能代替部署者设备。

在自己的空闲测试部署完成失败试验。涉及断上游、改预期值或重启服务的试验，会影响使用该链路的现有会话，不在共享活跃服务上直接执行。

| 编号 | 对象 | 最小通过证据 | 不能替代它的证据 |
| --- | --- | --- | --- |
| V1 | Windows 原始 7899 上游 | 三个目标分别观测 IP、国家、API CF-Ray POP | 通用代理可用、IP 页一次成功 |
| V2 | SSH 反向转发 | Linux 7899 对同三个目标实际请求符合预期 | 端口监听、SSH keepalive、前台无报错 |
| V3 | Linux gate / guard | 正常近期完整检查、正确 daemon/host/boot、监听有效 | `status=allowed` 单一字段或 service active |
| V4 | Linux namespace | 空间与宿主不同、只有预期接口、显式代理成功、普通直连失败 | 仅有代理变量、仅有一次直连超时 |
| V5 | Claude CLI | `ccen` 启动，V4 条件成立，真实模型回复 | API 根路径 401/404 |
| V6 | Claude 图形扩展 | 有效图形模式/wrapper 设置、实际子进程空间、模型回复 | 扩展已安装，或 CLI 成功 |
| V7 | Codex 指定后端 | 关联当前入口、逐 PID 检查代理/例外/TLS、真实请求结果 | 别的 app-server、工具 curl、仅设置了 http.proxy |
| V8 | Windows guard / AdsPower | App 来源明确、真实 profile 经守卫、独立协议与失败试验 | 截图绿灯、Linux gate 通过 |
| V9 | 断链与恢复 | 下文各场景符合状态机，无改换最终出口 | 一次正常请求或单纯监听重建 |

V8 的 Windows 源码和构建材料现已补齐，实际浏览器与设备仍须分别验收；V7 不包含 Codex 强制隔离能力。

## 2. 命令会做什么

| 命令 | 操作性质 | 返回值如何解读 |
| --- | --- | --- |
| `systemctl --user status ...` | 读取服务状态 | active 是服务状态，不能证明出口 |
| `claude-ip-guard status` | 读取当前状态 | 查看全部关键字段与原因，不据此自动判 PASS |
| `claude-ip-guard check` | 对原始上游发起真实 HTTPS 探测 | 单轮完整采样结果，不检查应用是否真的用了 gate |
| `claude-ip-guard enforce` | 可能启动服务、请求刷新、等待结果 | 完整近期状态验收；不是纯只读操作 |
| wrapper 中的测试请求 | 创建临时 scope/namespace 并联网 | 仅覆盖该测试进程的启动路径 |
| `ccen -p ...` | 交互确认后产生真实模型请求 | 网络、账号与模型路径的实际结果 |

## 3. 上游与 gate

先按 [代理与 SSH](proxy-and-ssh.md) 在 Windows、Linux 分别完成三目标探测，确认 API POP 来自 `api.anthropic.com`。随后在 Linux 执行：

```bash
systemctl --user status claude-ip-gate.service --no-pager
~/.local/bin/claude-ip-guard status
cat "/run/user/$(id -u)/claude-ip-gate/status"
journalctl --user -u claude-ip-gate.service -n 40 --no-pager
```

对准备验收的部署再执行 `claude-ip-guard check` 和 `enforce`。正常收据应包含正确的预期/观测 IP、国家、API POP、唯一上游 7899、当前 hostname/boot/daemon 以及有效 TCP/UDS。`reason` 应为完整成功，不能把瞬时失败保留监听时的 `allowed` 当成同样的结果。

状态文件是宿主本地观测，不建议把包含真实参数的全文发到公开 issue。保留私人完整收据，对外仅提交脱敏摘要。

## 4. 同一个 namespace 中做组合验证

以下命令在已安装并通过 gate 检查的 Linux 上执行。它会发出一次无账号的 ipify HTTPS 请求，并尝试无代理 IPv4/IPv6 TCP 连接；测试进程结束后 scope 退出。预期 IP 必须使用自己已核验的值。

```bash
CCEN_HOST_NETNS="$(readlink /proc/self/ns/net)"
read -r -p '已核验的固定出口 IPv4: ' CCEN_EXPECTED_IP
~/.local/bin/claude-net-sandbox /usr/bin/python3 - "$CCEN_HOST_NETNS" "$CCEN_EXPECTED_IP" <<'CCEN_NAMESPACE_PROBE'
import json, os, socket, sys, urllib.request

host_ns, expected_ip = sys.argv[1:]
current_ns = os.readlink('/proc/self/ns/net')
interfaces = sorted(name for _, name in socket.if_nameindex())
if current_ns == host_ns:
    raise SystemExit('FAIL: process still uses the host network namespace')
if interfaces != ['lo']:
    raise SystemExit('FAIL: unexpected interfaces inside private namespace')

direct = {}
for label, destination in (
    ('ipv4', ('1.1.1.1', 443)),
    ('ipv6', ('2606:4700:4700::1111', 443)),
):
    try:
        stream = socket.create_connection(destination, timeout=3)
    except OSError as error:
        direct[label] = {'blocked': True, 'errno': error.errno}
    else:
        stream.close()
        raise SystemExit('FAIL: ordinary direct connection succeeded: ' + label)

opener = urllib.request.build_opener(urllib.request.ProxyHandler({
    'http': 'http://127.0.0.1:17898',
    'https': 'http://127.0.0.1:17898',
}))
with opener.open('https://api.ipify.org', timeout=15) as response:
    observed_ip = response.read(256).decode('ascii').strip()
if observed_ip != expected_ip:
    raise SystemExit('FAIL: proxied public IP differs from expected value')
print(json.dumps({
    'result': 'PASS', 'different_netns': True,
    'interfaces': interfaces, 'direct': direct, 'proxy_ip_matches': True,
}, sort_keys=True))
CCEN_NAMESPACE_PROBE
```

四项组合才支持此处的 V4 结论。直连失败本身可能来自目标不可达，故不能删掉 namespace、接口和成功代理请求的条件。IPv6 不可用也只能证明该测试路径未成功，不能代替 Windows 或浏览器 IPv6 验收。测试没有覆盖文件访问、宿主 Unix socket、SSH relay 或恶意程序逃逸，边界见 [security.md](security.md)。

## 5. 应用分别验收

### Claude CLI

先用 `command -v ccen` 确认没有命中旧路径。普通终端中执行以下短请求并完成交互确认；它会产生一次真实模型调用：

```bash
ccen -p 'Reply with exactly CCEN_OK. Do not use tools.'
```

要求响应有预期标记，并确认实际进程来自 wrapper。直接运行官方 `claude` 符号链接不自动获得 CCEN 的外层保护。

### 图形插件与 Codex

按 [编辑器文档](editors.md) 检查**有效设置**和对应后端 PID。Claude 的终端模式不能用图形 wrapper 的验收代替；Codex 的工具命令出口不能证明模型请求出口。图形会话与每个独立 app-server 都保留各自记录，确认没有继承 wildcard NO_PROXY、冲突代理或关闭 TLS 的设置。

### Windows 与 AdsPower

按 [Windows](windows.md) 和 [AdsPower](adspower.md) 的前提完成源码及 profile 验收。HTTP 出口页仅覆盖该网页请求。WebRTC、UDP、DNS、IPv6 与扩展流量的结果分开记录；未测的项目填写“未测”，不写“无泄漏”。

## 6. 失败与恢复场景

| 场景 | 前提/触发 | 应观察到的实现行为 | 完成条件 |
| --- | --- | --- | --- |
| F1 冷启动无上游 | 独立测试部署首次 gate 启动前，7899 不可用 | 未取得完整成功，不开放监听 | 新连接不能被转到另一个公网出口 |
| F2 已观测身份 mismatch | 测试配置的预期值与真实结果不符 | 完成对应检查后关闭 gate、切断既有转发 | 时间戳、reason、新旧连接结果均记录 |
| F3 瞬时失败 | 先健康，再令测试上游探测超时 | 前两次保留监听和既有转发，也仍接受新连接；第三次关闭 | 不把“监听接受”误写成“外网请求成功” |
| F4 恢复正确上游 | 恢复同一个预期出口；手动隧道需自己重建 | gate 完整检查后重开，新连接可用 | 再验 IP/国家/API POP；旧流和旧会话不自动复活 |
| F5 TLS/身份头缺失 | 测试链路出现证书或 CF-Ray 问题 | 按探测失败类别处理，不能跳过验证 | 保留错误，不用 -k 或关闭 TLS 换取 PASS |
| F6 应用入口改变 | 切换终端模式/后台入口/其他 app-server | 可能不再经过原 wrapper | 新入口必须独立验证，否则标记未覆盖 |

F2 是“完成检测之后阻断”，不是出口变化那一刻的零延迟保证。F3 的容忍窗口是当前策略，测试不应把一次超时就断流作为通过标准。无瞬时时延承诺；记录触发、每次检查、关门和恢复时间，区分观测值与源码预算推算。

## 7. 由近到远定位故障

按“应用入口 → namespace/代理 → gate → R:7899 → SSH → W:7899 → 住宅上游 → API”定位，停在首个失败层。反向也可先确认 W 的上游，再向应用推进；关键是每步都使用对应位置的真实请求。

| 症状 | 优先核对 |
| --- | --- |
| CLI 与扩展行为不同 | PATH、图形/终端模式、有效 wrapper、进程所在主机、继承变量 |
| gate active 但启动失败 | reason 是否 degraded，boot/daemon/host 是否一致，检查是否新鲜 |
| IP 正确仍被拒绝 | 国家、API CF-Ray POP、证书、缺失响应头；不要误用网页 POP |
| R:7899 监听但请求超时 | W 原始请求、SSH owner/cgroup、残留会话、住宅高端口连接 |
| bwrap 无法启动 | 依赖、用户 manager、runtime、必需目录/locale、控制路径符号链接 |
| 一部分 Codex 后端可用 | 明确每个 app-server 的来源、PID、代理例外与 TLS 状态 |
| 旧 local-only 工具拒绝匹配 | 扩展版本已变化；不要对未知压缩 JS 强行替换 |

不要在不确定所有权时批量杀 sshd、改整份系统代理、覆盖 VS Code 配置或恢复直连。保存相关脱敏错误和配置版本后，修正首个失败层再重验。

## 8. 私人验收收据模板

```text
时间与时区：
设备/执行位置：W / R / N
仓库提交：
render-manifest.json SHA-256：
系统/依赖/CLI/扩展版本：
入口与实际后端标识：
预期 IP / 国家 / API POP：私人记录，对外脱敏
V1–V9：逐项 PASS / FAIL / 未测 / 不适用，并附证据
F1–F6：触发、检查、阻断、恢复时间及结果
可选 SSH relay / host-runner：未启用或明确列出
未覆盖入口与遗留问题：
```

已有维护者记录在 [inventory.md](inventory.md)。模板不要求公开原始认证、环境转储、完整日志或私人地址，公开结果使用脱敏摘要。
