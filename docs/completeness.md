# 交付状态

截至 2026-10-30，Windows 连接管理器源码、依赖文件、部署示例、独立构建入口和便携包已补齐；Linux 核心材料继续保留。源码与构建产物均不包含用户的代理账号、模型认证、浏览器 profile 或 SSH 私钥。

| 组件 | 已交付 | 验证范围 |
| --- | --- | --- |
| Windows GUI | 浏览器守卫、Claude/Codex 两条隧道、托盘、自启、状态与日志 | 本次 Windows x64 构建；原安装版有现场链路观测 |
| Node 守卫 | 完整源码、https-proxy-agent 依赖及 npm 锁文件 | 固定 IP/国家/节点核验；身份不符阻断、探测网络错误告警的行为来自现有实现 |
| 私人部署参数 | deployment.example.json、schema、Python/Node/界面共用参数 | 示例值不提供真实服务；实际值由使用者填写 |
| Mihomo 策略 | [最新脱敏全局扩展](../windows/clash/README.md)和基础示例 | 需填写自己的住宅认证并适配订阅节点名称 |
| Linux | CLI、gate、guard、namespace、PID1、systemd 和 renderer | 既有离线检查与历史现场观测，详见 inventory |
| Codex | 普通代理隧道、路径状态、独立恢复 | 不包含与 Claude 等价的强制 namespace 隔离 |
| 浏览器与设备 | 部署和分层验收说明 | 每台设备的 profile、UDP、DNS、自启和重启分别验收 |

Windows 工程在 [windows/manager](../windows/manager/README.md)，不再依赖先从维护者设备导出源码。可选的源码导出工具仍用于其他本地副本的交接，不能代替应用构建。

源码交付、构建完成、原安装版本的成功请求与参数化发布包在新设备上的端到端验收是不同结论。本次没有覆盖维护者正在使用的程序或改动其网络。现场与构建记录见 [inventory.md](inventory.md)，新设备按 [verification.md](verification.md) 检查。
