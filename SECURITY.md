# 安全策略 · Security Policy

## 支持的版本 · Supported versions

| 版本 | 状态 |
| --- | --- |
| 1.0.x | ✅ 支持（当前） |
| < 1.0 | ❌ 不再支持 |

## 报告漏洞 · Reporting a vulnerability

请不要在公开 Issue 中披露安全漏洞。请通过 GitHub 的
[私密漏洞报告](https://github.com/hengjunguo35-oss/GluePaw/security/advisories/new)
提交，或发邮件到 `254826111+hengjunguo35-oss@users.noreply.github.com`。

我们会在 7 天内确认，修复发布后会在 Release 说明中致谢（如你愿意）。

**Please do not disclose vulnerabilities in public issues.** Use GitHub's
[private vulnerability reporting](https://github.com/hengjunguo35-oss/GluePaw/security/advisories/new)
or email `254826111+hengjunguo35-oss@users.noreply.github.com`.
We aim to acknowledge within 7 days.

## 依赖与安全更新 · Dependencies

- 依赖由 `requirements.txt` 管理，保持在最新稳定版
- 发布前执行 `pip-audit -r requirements.txt`，当前结果：**无已知漏洞**（2026-11 审计）
- 更新依赖：

  ```bat
  python -m pip install -U -r requirements.txt
  ```

- 打包产物不联网、不需要管理员权限、不写入系统目录

## 数据与隐私 · Data & privacy

- 数据目录：`%LOCALAPPDATA%\GluePaw`
- 普通历史使用 Fernet（AES-128-CBC + HMAC）加密落库
- 主密钥在 Windows 上由 DPAPI 保护，换机器无法解密
- 敏感内容只存内存并倒计时，私钥类内容直接丢弃
- 程序全程无网络请求

## 已知限制 · Known limitations

- exe 未做代码签名，首次运行会触发 SmartScreen 提示；
  下载后请用发布页的 `SHA256SUMS.txt` 核对文件完整性
