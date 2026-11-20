# AdsPower：浏览器连接到 Windows 守卫

## 当前链路与证据边界

当前源码的数据路径是：

```text
AdsPower 浏览器环境
    → Windows 本地守卫 127.0.0.1:17899
    → Windows 本地 HTTP 上游 127.0.0.1:7899
    → 用户自己的固定出口
```

完整的 Windows 守卫源码已收录，见 [Windows 软件](windows.md)。17899 是 HTTP 守卫，7899 是它的本机 HTTP 上游；出口参数由 deployment.json 提供。源码可读不代替每个实际浏览器 profile 的链路验证。

## 部署顺序与前置条件

先配置 Windows 专用上游，再运行 [连接管理器](windows.md)核验守卫，最后接入浏览器。代理与 SSH 的配置见 [proxy-and-ssh.md](proxy-and-ssh.md)。

1. 在自己的 Windows 上安装 AdsPower 与实际使用的代理客户端；代理账户、浏览器登录和期望出口都使用自己的数据。
2. 先在应用尚未接管浏览器前，确认自己的上游代理可用，并记录从该上游观察到的期望 IP、国家/地区和节点信息。不要复制仓库维护者的 IP、代理口令或浏览器资料。
3. 取得并审阅管理器源码后，按实际配置启动守卫，确认监听的是 `127.0.0.1` 而非未经限制的 `0.0.0.0`。端口若调整，AdsPower 与应用配置必须一起调整。
4. 为该用途新建独立的 AdsPower 浏览器环境，在其代理设置中填入守卫的实际协议、主机和端口。当前守卫入站是 HTTP CONNECT，不是 SOCKS5。
5. 守卫使用 HTTP，主机为 `127.0.0.1`，示例端口为 `17899`。本地守卫未实现认证时不要填写上游代理账户口令。代理账户口令应只保存在私有上游配置中。
6. 先运行 AdsPower 自带的连接/代理检查，再在这个环境打开出口检查页。将观察值与自己记录的期望出口比较；界面出现“成功”不代替数值核对。
7. 在隔离的测试环境中完成下表的阻断试验，保存脱敏日志与时间戳后，再用于实际浏览。

## Windows 上分别检查上游和守卫

以下示例假定使用历史端口，均是只读检查；应按实际配置替换。先看监听地址与端口，不停止或重启当前 App：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 7899,17899 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

正常情况下这两个专用入口应只绑定 loopback。不存在监听时先查管理器/上游是否启动；监听属于其他程序时先解决端口冲突，不随意结束未知进程。存在监听只能说明有程序占用端口，下一步必须发真实请求。

检查专用上游：

```powershell
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:7899 --connect-timeout 5 --max-time 15 https://api.ipify.org
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:7899 --connect-timeout 5 --max-time 15 https://claude.ai/cdn-cgi/trace
```

先将 IP、trace 的 `ip`、`loc` 和 `colo` 与自己期望的出口契约核对。`colo` 是探测域名所到达的 Cloudflare 节点，不能单独证明住宅地址或账号身份。前述 `--%` 适用于 Windows PowerShell，保留 `--noproxy` 的空参数；不要把这一整行原样用于 Bash。

**完整源码确认守卫入站支持 HTTP 后**，再通过守卫请求同一个目标：

```powershell
curl.exe --% --disable --noproxy "" --proxy http://127.0.0.1:17899 --connect-timeout 5 --max-time 15 https://claude.ai/cdn-cgi/trace
```

只有上游和守卫两次观测都符合各自契约，才将独立 AdsPower 环境接到守卫。守卫也可能有目标域名限制，不能把访问任意 IP 检查站被拒绝直接判为故障；具体允许目标需要源码确认。不要因为验证失败就把浏览器改接通用代理或删除代理设置来继续使用。

在已配置的 AdsPower 环境内打开 `https://claude.ai/cdn-cgi/trace`，记录与上面命令是否一致；这一步验证的是浏览器环境自身。PowerShell 成功不能代替浏览器内请求成功，AdsPower 的代理检测页也可能使用不同的目标站。对外分享记录时将完整公网 IP、代理账户、profile 标识脱敏。

## 协议、WebRTC 与环境设置

AdsPower 支持 HTTP、HTTPS、SOCKS5 等代理类型；所选类型必须与守卫的实际监听协议一致。具体输入项和连接检查见 [官方代理设置说明](https://help.adspower.com/docs/proxy_types)。软件版本和 UI 会变化；本仓库中的端口来自这套自建管理器，不是 AdsPower 默认端口。

WebRTC 需要另外配置。AdsPower 官方将 `Disabled` 描述为禁用 WebRTC，将 `Real` 描述为使用真实地址，`Replace` 则使用代理地址替换可见地址。若这个环境无需语音/视频等 WebRTC 功能，可选择禁用，并验证实际行为；这可能影响依赖 WebRTC 的网页功能。选择其他模式时，根据用途测试地址暴露与 UDP 路径，不能仅凭 HTTP 出口页作判断。参见 [官方 WebRTC 模式说明](https://help.adspower.com/docs/How-to-choose-WebRTC-mode)。本次未核实 AdsPower 的 DNS 路由实现，因此不承诺 DNS 全部经过守卫。

## 验收与故障定位

| 现象/试验 | 先核对什么 | 可接受结果或下一步 |
| --- | --- | --- |
| 浏览器无法联网 | 守卫是否监听、配置协议是否一致、上游能否被探测 | 不绕过守卫直接切到系统网络；先定位失败环节 |
| AdsPower 代理检查成功 | 环境实际出口、代理协议、测试 URL | 只有观察值符合预期才继续；供应商连通检查不等于管理器已验证 |
| 本地守卫停止 | 仅停止独立测试实例，打开新测试请求 | 请求失败，不自动改为直连 |
| 上游出口不匹配 | 用独立测试上游触发，观察新连接 | 拒绝转发到不符合预期的出口 |
| 存量连接遇到出口变化 | 记录连接、变更与关闭时间戳 | 证实已有连接是否被终止；截图写的 10 秒轮询存在检测窗口 |
| 浏览器 IP 对、其他应用不同 | 独立检查该应用实际运行主机及代理路径 | 按各自的链路验收；AdsPower 配置不会自动保护 VS Code/Codex |
| WebRTC、DNS、IPv6 路径 | 检查 AdsPower 对应设置与实际请求 | HTTP 探测不能证明这些协议已被拦截，需单独观察 |

故障注入必须在独立的测试守卫/上游和新 profile 中完成。停止守卫、关闭上游或改变出口前，确认没有其他工作复用这些端口。记录测试时刻、目标 URL、实际 IP/地区、连接结果、日志事件，以及旧连接在多长时间后关闭；恢复正常后重新核验再放行。没有独立实例时先保持当前运行环境，不能为完成验收直接切断共享代理。

将“首次请求不放行”“新连接是否拒绝”“已建立连接是否终止”分别记录。浏览器缓存、HTTP 连接复用与已有标签页可能造成误判，测试应使用新的请求和明确的时间戳；不要用网页仍显示旧内容来判断网络仍可用，也不要把页面报错自动解释为守卫已经阻断。

浏览器环境应使用各自独立的登录资料，不要导出或上传 Cookies、Local Storage、浏览器指纹配置、代理凭据或 AdsPower 的本地数据目录。无需为了手工配置代理向网络开放 AdsPower Local API；若以后增加 API 自动化，再核对其认证、监听范围与调用权限。

该 profile 的手工代理设置不会自动配置其他 profile、AdsPower 主程序更新请求、操作系统、VS Code Remote 后端或 Codex/Claude 扩展。扩展实际运行在哪台主机，就在那台主机核对对应链路，见 [编辑器接入](editors.md)；远端依赖的 SSH 转发见 [代理与 SSH](proxy-and-ssh.md)。

## 这套守卫能证明什么

完整实现和故障测试通过后，能报告的是“经过该守卫的特定流量在测试条件下符合出口约束”。只有一次 `claude.ai/cdn-cgi/trace` 核验时，能报告的是该请求观察到的出口；不能由此推出全部浏览器协议均受到约束。

固定出口和环境隔离可以减少意外路由变化，但不验证账号权限或服务可用性。网络出口验收和真实应用请求的结果应分别记录。
