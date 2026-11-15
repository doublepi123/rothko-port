# 源码持续检查

[Source checks](https://github.com/doublepi123/rothko-port/actions/workflows/source-checks.yml)
在 main 推送、PR、手动触发和每日 **19:23 UTC（北京时间次日 03:23）**
运行。定时任务使用默认分支，可能延迟；公开仓库长期无活动时 GitHub
可能停用 schedule，不能当作精确计时服务。

## 每次检查什么

| 检查 | 真实执行内容 |
| --- | --- |
| Source and installer | 跟踪文件的 XML/JSON/Python/shell 语法、文档相对链接、补丁索引、排除的二进制/密钥/私有路径标记 |
| 接入脚本 | 安装两树、相同目录重复调用、冲突前置拒绝、符号链接目标拒绝 |
| 八项目补丁矩阵 | 从公开上游取得 BASES.tsv 的精确提交，在真实 Git index 中逐个应用该项目的补丁 |

补丁矩阵从 `patches/BASES.tsv` 派生，不复制一份项目清单。
每天验证冻结基线，不自动合并上游的新提交；维护者更新基线后再次运行。
网络或上游提交不可取时会失败，不会重试到另一个未声明的来源。

本地复现：

```bash
uv run --no-project tools/check-source.py
bash tools/check-install.sh
bash tools/check-patch.sh android_hardware_xiaomi
```

源码检查通过 PEP 723 声明固定的 `defusedxml` 依赖，禁止 XML DTD/实体展开；
CI 固定 uv 版本。第三个命令需要网络，临时克隆在退出时清理。它用 `git apply --cached`
验证补丁内容，不运行 Android 编译器或设备程序。

## 权限和资源

只使用 GitHub-hosted `ubuntu-24.04`，`contents: read`，
checkout Action 固定到提交且不保留凭据。不使用 `pull_request_target`、
自托管机器、SSH/签名密钥或手机连接。PR 代码只在临时托管环境中运行。

## 绿灯不代表什么

这里**没有每日 ROM 构建或自动刷机包发布**，也没有完整 Soong 编译。
绿灯仅说明源码交付检查和固定基线补丁应用通过，不证明 SELinux/VINTF、
整机可复现、硬件兼容性、运行功耗或官方设备准入。
正式模块/整机构建仍需独立的大容量构建环境和已核实的固件输入；
完整差距见 [构建说明](BUILDING.md) 和 [官方准备](OFFICIAL-READINESS.md)。
