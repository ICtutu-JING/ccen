# 2026-10-30 Windows 软件与策略更新

本次直接从 Windows 原工程导入连接管理器，补齐 windows/manager 的 Python 入口、后台维护、界面、Node 守卫、依赖文件、npm 锁文件、部署模板和独立构建脚本。Windows 真实主机与出口参数改为 EXE 同目录的私人 deployment.json；本机安装程序、状态和认证未上传或覆盖。

构建环境为 Windows x64、Python 3.10.11、Node 24.14.0、PyInstaller 6.16.0、pywebview 6.0、pystray 0.19.5、Pillow 11.3.0、pythonnet 3.1.0。Windows 便携包已从导入后的源码构建，包含无凭据的示例部署配置。下载入口见 [Windows 软件](windows.md)。

本次未增加自动化回归测试、未向活跃链路注入故障。仅执行构建、源码/脚本语法与文档检查，以及发布文件的凭据排除检查。既有仓库 CI 仍按原工作流运行，其结果与本次 Windows 构建分别记录。

原安装版本在 10 月 29 日完成两条代理隧道托管，关闭主窗口后仍保持进程和转发；10 月 30 日住宅上游短暂故障自行恢复后，本机与远端守卫再次核验通过，并收到真实 Claude 模型回复。这里的现场记录属于原安装版本，不将其冒充参数化发布包在其他设备上的验收。

最新 Mihomo 全局扩展的脱敏模板放在 windows/clash，包含 Claude/Meta/Muse/Gmail 住宅路由、OpenAI 普通代理、浏览器 TCP 守卫与 UDP 规则，以及住宅链自动主备。模板的住宅认证与校园网络例外需由使用者填写。

以下保留 2026-10-16 的历史整理记录，其中当时缺少 Windows 源码的描述不代表当前交付状态。

---

# 2026-10-16 整理、复核与验证记录

## 1. 版本和范围

原仓库 main 基线为 `389e50c4d5cb7b82051d8d0fd07fa0bac8224fa8`。第一版整理提交为 `8d9d775`，补充 Windows 命令兼容性与传输说明后为 `d15e735`。后续复核针对发布副本继续完善；实际获取时以 Git 提交和该提交的 Actions 结果为准。

取证环境为 Linux fpga04，读取了用户安装的 CCEN 代码、systemd 用户单元、相关编辑器声明/配置和选定后端的网络参数。Windows 安装资料和有限历史代码仅作为来源线索，当前没有 Windows 磁盘执行通道，也没有取得原工程导出副本。

仓库保持原有私有访问状态与分支，没有改写历史、强推或自动邀请协作者。文档的使用对象是所有部署者，仓库访问授权不代替服务器、代理或服务账号权限。

## 2. 已观测的环境基线

以下版本由 2026-10-16 的只读命令取得，表示原安装环境，不是所有版本均已兼容的保证，也不是依赖锁文件：

| 项目 | 观测值 |
| --- | --- |
| OS / kernel | Ubuntu 22.04.5 LTS / 5.15.0-164-generic |
| Python | 3.10.12 |
| Bash | 5.1.16 |
| bubblewrap | 0.6.1 |
| curl | 7.81.0 |
| systemd | 249，Ubuntu 249.11-0ubuntu3.22 |
| OpenSSH | 8.9p1，Ubuntu 3ubuntu0.17 |
| Linux gate / 两个基础 SSH relay | 盘点时 active |
| host-runner service / socket | 盘点时 inactive |

编辑器的磁盘安装版、实际运行版、代理/namespace 观测分别记录在 [editors.md](editors.md)。Windows 运行时和构建依赖仍未知，不从 EXE 文件形态推断。

## 3. 安装版同步及第一版发布改动

- 当前安装 gate 已只允许专用上游 7899，取消通用规则端口候选；Cloudflare 自身 POP 只记录，仍检查 IP/国家和 API CF-Ray POP。
- 当前安装 gate 有连续三次瞬时错误阈值；前两次保留监听，也允许新连接。
- 已安装环境有本机和明确目标的实验室 SSH relay；它们是可选宿主权限通道，不是普通部署前提。
- 原 CLI 还保留 Cloudflare 自身 POP 检查及过期的 60 秒描述；发布副本统一语义和表述，并让 guard 的状态契约只接受 7899。
- 个人 HOME、UID、IP 和 SSH 映射改为参数；renderer 写新的私人 staging，同时记录模板/输出哈希。发布副本不是安装文件的字节相同复制。

## 4. 第二轮完整性复核

复核从“新设备是否具备全部材料”出发，发现并处理以下问题；这些改动只应用于仓库副本，没有安装到现有运行目录：

| 问题 | 发布副本处理 |
| --- | --- |
| Linux CLI 隐式依赖个人 `singapore-env.sh` | 移除未声明的脚本读取，显式设置与 wrapper 一致的 locale |
| 诊断输出可能直接打印带口令的代理变量 | 仅报告变量存在，不打印值 |
| CLI 启动探测的协议与等待预算需完整声明 | 在已有固定代理、忽略 curlrc 和清空 no-proxy 的基础上，补充 HTTPS 限制与连接超时，并回归验证 |
| 部分控制路径为 symlink 时悄悄跳过保护 | 对不支持的控制路径/祖先 symlink 拒绝启动；官方 CLI 的可执行版本链接单独允许 |
| 必需的空控制目录和精确安装文件表未声明 | 清单列出目录、文件、组件、目的路径和权限；文档给出备份/安装/回滚/卸载流程 |
| Claude 图形 wrapper 与终端模式混淆 | 模板显式 `claudeCode.useTerminal=false`，要求检查有效设置和实际进程 |
| Codex 代理例外/TLS 可能被继承 | 模板保持 TLS 验证，并要求逐后端检查，仍不声称强制隔离 |
| API POP 取得步骤只给网页 trace | 明确三目标命令，以 API 的 CF-Ray 作为 Linux gate 参数 |
| Windows 精选导出静默遗漏必要元数据 | 增加遗漏清单与完成标记，逐项补回合法依赖、模块和模板 |
| Windows 源/目标路径的 junction 祖先 | 增加拒绝检查和合成回归 |
| 文档缺统一路线与完成标准 | 增加 onboarding / completeness，重写原理、失败行为和验收矩阵 |

完整的状态边界见 [architecture.md](architecture.md)，材料缺口见 [completeness.md](completeness.md)。

## 5. 验证记录的解释

第一版 [b67c96e 的 Actions](https://github.com/Kevin-the-Great/ccen/actions/runs/38884355794) 通过了当时的 15 项 Linux 离线测试及 Windows PowerShell 5.1 / PowerShell 7 合成导出测试。[d15e735 的 Actions](https://github.com/Kevin-the-Great/ccen/actions/runs/38884472367) 同样通过。这些是已完成的历史结果；第二轮修改必须由新提交的 CI 重新验证。

第二轮本地 Linux 的 22 项离线测试已通过，覆盖渲染、哈希、缺参/非法值/覆盖拒绝、受控上游和 gate 状态机，并增加控制路径、参数/stdio 与无隐式配置依赖的验证。Windows 测试用临时合成工程检查白名单、排除/遗漏、清单、凭据提前阻断、不覆盖、相对路径及 junction，修改后的 Windows 结果以对应提交 CI 为准。它们不读取个人 Windows 源码、不执行真实模型请求、不证明真实 bwrap 内核隔离，也不构建原版 App。

发布前另核对 Markdown 链接/围栏、示例语法、受众措辞、待提交源码、常见秘密格式及意外二进制/私人配置。此类检查不构成完整 Git 历史无秘密的证明。

## 6. 操作偏差与现场影响核对

第二轮生成文档时，一处 heredoc 边界错误使部分文档命令被 shell 解释，误执行了 `systemctl --user daemon-reload` 和对既有 gate 的 `enable --now`。目标安装变量未设置，复制尝试指向 `/.local` / `/.config` 并因权限拒绝，未成功覆盖安装代码。之后的文档写入改为文件补丁。

只读核对结果：gate 保持原 `MainPID=3546052`，启动时间仍为 `2026-09-26 00:10:05 +08`；已启用链接时间仍为 `2026-07-30 12:32:46 +08`，已安装 gate、sandbox 和 unit 的修改时间均未变。没有发生 gate 重启、启用状态变化或已安装源码覆盖。配置重载确实执行过，因此不能将本轮描述成完全没有调用 systemd 的操作。

没有对活跃上游注入故障，没有构建/安装 Windows App，也没有中断实验任务。新部署的完整端到端结果仍需按 [verification.md](verification.md) 单独取得。
