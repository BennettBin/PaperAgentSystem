# 阶段 I 安全报告

覆盖范围：

- Workspace 越权、绝对路径、`..` 和符号链接逃逸。
- Prompt Injection、角色伪造、Tool/命令注入、数据外传与删除指令。
- 可执行文件签名、扩展名、MIME 不匹配和 PDF 主动内容。
- 生成脚本不可执行，普通 Worker 不运行代码或 LaTeX。
- Trace 中 Prompt、正文、响应、密钥和令牌脱敏。

固定攻击样例的 Prompt Injection 阻断率为 100%（验收门槛 95%），路径逃逸成功数为
0。禁用型 `SandboxExecutor` 对 Python、Shell、PowerShell 和 LaTeX 统一返回
`sandbox_execution_not_supported`。

本报告只覆盖仓库内确定性安全回归。生产前仍需对真实反向代理、身份提供方、容器运行时、
依赖镜像和网络策略做独立渗透测试与供应链扫描。
