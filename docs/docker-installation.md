# 本机 Docker 安装记录（2026-10-09）

项目目录：`D:\vibe coding\ai-01`。

**状态更新：用户已完成安装，现已启动 Docker Desktop Linux 引擎及项目。无需重复安装。原生 Compose、后端 26 项测试、前端锁文件安装、浏览器完整流程与重启持久化均已验证；当前结果和演示密码待授权恢复事项见 [目标环境验收](target-verification.md)。下文保留首次安装失败的历史记录。**

已完成：下载官方 Windows x86_64 Docker Desktop 4.94.0.241994 安装器（635493296 字节）；Authenticode 签名为 Valid，签名方 Docker Inc。嵌入 7z 的起始头和下一头 CRC 校验通过。

安装器保存在 `D:\vibe coding\work\docker-install\Docker Desktop Installer.exe`。

Windows 报告版本 10.0.26200；`wsl --version` 报告 WSL 2.6.3.0。受限执行终端无法使用 CIM 检查硬件虚拟化，WSL 状态访问也曾返回 E_ACCESSDENIED；这些结果不能证明主机未启用虚拟化或 WSL。

安装尝试：官方当前用户安装参数 `install --user --quiet --accept-license --backend=wsl-2`。授权安装目录、配置目录和临时目录后仍在自解压阶段退出，返回码 -5；新安装日志未产生。使用工作区临时目录与恢复官方文件名也未解决。退出码原因尚未由安装日志证实，可能与受限执行环境有关。Docker Desktop 尚未安装成功，Compose 和项目启动尚未执行。

## 在用户自己的 PowerShell 中继续

```powershell
# 启动已验证的官方安装器；使用当前用户安装模式。
Start-Process -FilePath 'D:\vibe coding\work\docker-install\Docker Desktop Installer.exe' -ArgumentList 'install','--user' -Wait
# 安装完成后从开始菜单启动 Docker Desktop，完成首次引导并等待引擎就绪。
Set-Location 'D:\vibe coding\ai-01'
powershell -File .\scripts\start.ps1 -Test
```

若提示需要启用 WSL 或重启，按安装界面要求完成后再运行启动脚本。不要删除数据库卷。启动成功地址为 http://localhost:8080；演示密码在本地 `.env` 中。

启动脚本已通过 PowerShell 语法解析；运行结果、原生 PostgreSQL/Redis 测试和持久化验收仍待 Docker 引擎可用后记录，不以既往替代环境的测试结果代替。

参考：[Docker 官方 Windows 安装文档](https://docs.docker.com/desktop/setup/install/windows-install/)。
