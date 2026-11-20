# Windows 连接管理器：下载、配置与构建

2026-10-30 已从 Windows 原工程导入 [windows/manager](../windows/manager)。此前只有 EXE、尚未取得源码的限制已经解除。

## 下载和运行

1. 下载 [Windows x64 便携版](https://github.com/ICtutu-JING/ccen/releases/tag/windows-2026.11.20)，完整解压后运行 `ClaudeConnectionManager.exe`。需要 Windows 10（1809 或更高）/11、OpenSSH Client 和 WebView2 Runtime。
2. 让 Windows 上的 HTTP 住宅代理监听 `127.0.0.1:7899`，普通代理监听 `127.0.0.1:7897`。在 EXE 同目录的 `deployment.json` 填入实际固定出口 IP、国家和 Claude 节点，保存后重开应用。
3. 在新电脑生成或准备 SSH 密钥，通过平台入口核实实际 Linux 用户和家目录，并把新机公钥授权给该账户。目标还要允许 SSH 转发、运行内部 SSH 端口 22，并在其登录环境中提供 `python3`、`curl`、`codex` 和 `claude`。
4. 点 **我的服务器 → 添加服务器**，填写平台地址、用户名、端口，以及实际 Linux 用户、家目录和本机私钥文件路径。点“保存并连接”，在 Windows 密码窗口按 **Ctrl+V** 粘贴当次平台密码。首次提示主机身份时核对指纹。
5. 成功后应用生成 `ccen` SSH 入口。从 Codex 的连接设置启用 `ccen`，或在 Claude Code 的 SSH 环境选它，再选远端项目。用一次只读请求验证应用确实在远端执行。
6. 同一 Linux 用户和家目录内换节点时点“更换节点”。输入新的平台端点和密码，应用会重新登录，即使平台地址和用户名与上次相同。

发布包中的 IP 是文档示例，不能作为实际住宅代理使用。包内没有代理认证、SSH 私钥、模型登录或浏览器 profile。

## 连接职责

| 组件 | 路径 |
| --- | --- |
| 浏览器 | AdsPower HTTP 17899 → 本机守卫 → Windows 住宅 7899 |
| Claude Code 图形 SSH 会话 | 远端 17899 → SSH → Windows 17899 守卫 → 固定住宅 7899 |
| Linux gate 部署 | Linux gate 17898 → Linux 住宅 7899 → SSH → Windows 住宅 7899 |
| Codex | Linux 普通代理 7897 → SSH → Windows 普通代理 7897 |

图形连接在远端应用的 Claude 启动环境中使用 `http://127.0.0.1:17899`，Codex 使用 `http://127.0.0.1:7897`。配置已有的 Linux gate 时使用 `7899`，端口 `17898` 留在 Linux 上。已有的手动 SSH 别名部署仍可按 [原有配置方式](../windows/manager/README.md) 使用。Mihomo 的进程、域名和 DNS 规则仍按 [代理与 SSH](proxy-and-ssh.md) 配置。

浏览器守卫只管理接入它的 TCP 连接，WebRTC、UDP、DNS 与其他程序分别配置和验收。图形连接模式会检查 OpenAI 授权服务能否访问。登录仍由目标 Linux 用户完成，首次使用项目时应发送只读请求实测。

## 构建

源码包括 Python GUI 与维护模块、HTML/CSS/JS、Node 守卫、只读监控器、图标生成器、Python 依赖版本、npm 锁文件、部署示例和 schema、构建脚本及第三方说明。

```powershell
cd windows\manager
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1
```

输出为 windows/manager/dist/ClaudeConnectionManager，必须保留整个目录。构建不依赖其他项目的虚拟环境。已使用的版本及源码运行方法见 [软件 README](../windows/manager/README.md)。

真实部署文件、运行状态、日志、浏览器目录和认证文件不提交。修改部署参数前先从托盘退出旧版，修改后重新启动。

## 托盘、自启和卸载

关闭窗口隐藏到托盘；托盘退出会停止其管理的守卫和专用隧道，包括接管的专用进程。暂停自动恢复保留当前连接。自启开关操作当前用户注册表 Run 项。

更新时先退出旧版，再启动新目录；不要同时运行维护相同端口的旧计划任务。卸载时先关闭自启，再退出管理器，最后删除解压目录。自己的 SSH 和代理配置仍由各自工具维护。

更新后从“我的服务器”管理图形连接。断线后点击“连接服务器”再输入当次平台密码。验证记录见 [inventory.md](inventory.md)；各设备的浏览器、重启、自启及网络隔离按 [verification.md](verification.md) 验收。
