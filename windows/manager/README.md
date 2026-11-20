# Claude / Codex 连接管理器

Windows 托盘软件，统一维护浏览器固定出口守卫、Linux Claude 住宅隧道，以及 Codex 普通代理隧道。窗口关闭后继续在托盘运行，SSH 子进程不占用终端窗口。

## 下载和运行

1. 下载 [Windows 便携包](https://github.com/ICtutu-JING/ccen/releases/tag/v2026.10.30)，解压整个目录。
2. 编辑 EXE 同目录的 `deployment.json`，填写自己的 SSH 别名、固定出口 IP、国家、Claude 节点和远端工作目录。示例 IP 不能联网使用。
3. 先配置 Windows 的本机住宅代理 `127.0.0.1:7899`、普通代理 `127.0.0.1:7897`，并部署仓库的 Linux gate。确认 SSH 别名能通过现有密钥免交互连接。
4. 双击 `ClaudeConnectionManager.exe`，分别启用浏览器守卫、Claude 和 Codex 自动恢复。
5. AdsPower 中将目标 profile 原生代理设为 HTTP `127.0.0.1:17899`，账号密码留空。

需要 Windows 10/11、Microsoft Edge WebView2 Runtime 和 Windows OpenSSH。便携包自带 Python 与 Node；不包含住宅代理服务、代理密码、SSH 密钥、Claude/Codex 登录或浏览器 profile。

## 部署配置

```json
{
  "ssh_alias": "my-linux",
  "expected_ip": "203.0.113.10",
  "expected_country": "US",
  "expected_colo": "LAX",
  "remote_path": "/home/your-user"
}
```

`expected_country` 是两个大写字母的国家码，`expected_colo` 是实测 Claude trace / Anthropic 节点。远端 Linux gate 必须使用相同的预期 IP、国家和 API 节点。修改配置前，先在托盘退出旧管理器；修改后重新启动。必需字段缺失会报错，不会自动改走其他出口。

固定端口职责：浏览器 `17899` → Windows 住宅 `7899`；Linux Claude gate `17898` → Linux 住宅 `7899` → Windows 住宅 `7899`；Linux Codex `7897` → Windows 普通代理 `7897`。`17898` 是 gate，不建立它的 SSH 转发。

## 已有连接和退出

- 启动时接管当前用户的浏览器守卫和精确匹配 SSH 别名、端口的专用 `-NT -R` 转发；不重启 VS Code、远端 app-server 或计算任务。
- 两条隧道分别开关自动恢复。暂停自动恢复会保留当前连接。
- 本机专用进程消失而远端仍占端口时，只释放确认全部由 sshd 组成、且当前用户的转发 PID 唯一的遗留会话。不会结束含有其他任务的会话。
- 关闭窗口缩到托盘；托盘“退出并停止本应用托管服务”才会停止其管理的守卫和专用隧道，包括启动时接管的进程。
- 登录 Windows 后启动使用当前用户的注册表 Run 项。卸载前先在界面关闭自启，再从托盘退出，最后删除解压目录。

## 界面状态的含义

浏览器守卫检查 ipify 与 Claude trace 的固定 IP、国家和节点。身份不符时关闭现有转发；成功核验后的独立探测网络错误显示告警，固定上游转发继续，已有结果不会当作新的核验通过。

远端 Claude 卡片读取 Linux gate 状态。Codex 卡片通过普通代理向 ChatGPT 发出 HEAD 请求；“代理可用”表示网络路径可达，不等于模型已经回复。日常检查不发送模型消息。

状态、设置和日志写入 `%APPDATA%\ClaudeConnectionManager`。配置与运行目录不随软件发布。可选只读监控器为 `watch.py` / `watch_remote.py`，不自动修复或重启服务。

## 从源码构建

已用于本次构建的环境：Windows x64、Python 3.10.11、Node 24.14.0。构建工具与 Python 直接依赖在 requirements 文件中固定版本，Node 依赖由 npm lock 文件固定。系统前提和其他设备的实际链路仍需各自验证。

```powershell
cd windows\manager
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1
```

构建结果在 `dist\ClaudeConnectionManager`，必须分发整个目录。脚本依赖本项目虚拟环境和 PATH 中的 Node/npm；也可使用 `-Python`、`-Node` 指定现有构建工具，不依赖 HpcCodexManager 工程。构建会放入无凭据的示例 `deployment.json`，不会复制本机真实配置。

调试运行前，将 `deployment.example.json` 复制为被 Git 忽略的 `deployment.json` 并填写自己的值，再执行 `python app.pyw`。
