# Windows 连接管理器：下载、配置与构建

2026-10-30 已从 Windows 原工程导入 [windows/manager](../windows/manager)。此前只有 EXE、尚未取得源码的限制已经解除。

## 下载和运行

1. 下载 [v2026.10.30 便携版](https://github.com/ICtutu-JING/ccen/releases/tag/v2026.10.30)，解压整个目录。
2. 按 [软件说明](../windows/manager/README.md) 编辑 EXE 同目录的 deployment.json，填写自己的 SSH 别名、固定出口 IP、国家、Claude 节点和远端工作目录。
3. 确认 Windows OpenSSH、WebView2 Runtime、本机住宅代理 7899 和普通代理 7897 可用，SSH 别名支持现有密钥免交互连接。
4. 部署并核验 [Linux gate](linux.md)，其预期出口与 Windows 配置一致。
5. 运行 ClaudeConnectionManager.exe，分别启用需要的守卫和自动恢复；浏览器按 [AdsPower](adspower.md) 设置。

发布包中的 IP 是文档示例，不能作为实际住宅代理使用。包内没有代理认证、SSH 私钥、模型登录或浏览器 profile。

## 连接职责

| 组件 | 路径 |
| --- | --- |
| 浏览器 | AdsPower HTTP 17899 → 本机守卫 → Windows 住宅 7899 |
| Claude | Linux gate 17898 → Linux 住宅 7899 → SSH → Windows 住宅 7899 |
| Codex | Linux 普通代理 7897 → SSH → Windows 普通代理 7897 |

17898 不做 SSH 转发。软件读取已有 SSH 别名，不写入代理密码，不修改 Clash 配置。Mihomo 的进程、域名和 DNS 规则仍按 [代理与 SSH](proxy-and-ssh.md) 配置。

浏览器守卫只管理接入它的 TCP 连接，WebRTC、UDP、DNS 与其他程序分别配置和验收。Codex 卡片通过 ChatGPT HEAD 请求检查网络，不发送模型消息。

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

本次上传未覆盖当前安装目录。验证记录见 [inventory.md](inventory.md)；各设备的浏览器、重启、自启及网络隔离按 [verification.md](verification.md) 验收。
