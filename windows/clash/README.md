# Mihomo / Clash Verge 全局扩展

global-extension.js 是 2026-10-30 从当前运行方案整理的脱敏模板：

- Claude/Anthropic、Meta/Muse、Gmail/登录及相关资源走固定住宅组。
- OpenAI/ChatGPT/Codex 走独立普通 proxy 组。
- SunBrowser TCP 经本地浏览器守卫 17899；相关 UDP 流量拒绝。
- 7899 是住宅专用 listener；7897 是普通代理入口。
- 住宅链自动主备切换前置节点，最终住宅地址保持不变。
- 住宅 DNS 策略、TUN 与嗅探设置随脚本生成。

导入前将 RES 中的示例 IP、用户名和密码替换为自己的住宅代理，并同步 LOCKED_RESIDENTIAL_IP 与管理器 deployment.json。真实配置不提交 Git。campusIpCidrs 默认空，按自己的校园 SSH 和设备补充。自动主备的节点名称来自当前方案，其他订阅需要调整名称匹配。

将填写后的私人副本接入 Clash Verge 的全局扩展。配置重载可能影响已有连接，在适合更新的时间操作；本次仓库更新没有重载维护者的 Clash。

软件构建与使用见 [连接管理器](../manager/README.md)，完整链路见 [代理与 SSH](../../docs/proxy-and-ssh.md)。
