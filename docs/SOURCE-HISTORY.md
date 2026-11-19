# 源码来源与历史合并

本仓库由三份已整理的本地源码仓库非压缩合并而来：

| 原仓库 | 导入基点 | 当前目录 |
| --- | --- | --- |
| rothko-port | `d554427c29a904efac7535fd6bd3be7dd0ef3369` | 顶层 |
| android_device_xiaomi_rothko | `1de424b8cd8c397ddb613bbd539f1eb61b477e6f` | device/xiaomi/rothko |
| android_vendor_xiaomi_rothko | `e7befb1b255893392cb9eb84f9f78d7191ad6545` | vendor/xiaomi/rothko |

三份原提交及作者仍可从 main 到达，没有 squash、rebase 或重写原始
提交。两次导入是保留父提交的合并；子树导入时与原树字节一致。
较早设备/厂商提交中的文件路径仍相对于各自当时的仓库根，这是保留
原始提交 ID 的结果。

后续只做目录、文档与源码接入整理。镜像工具移到 `tools/image`，
补丁入口移到 `tools/apply-patches.sh`。

活动上游项目的补丁继续保留各自作者、版权头、来源地址和精确基点，
见 `patches/BASES.tsv`。Lineage/AOSP 的完整源码历史不重复装进本仓库。
旧 Rust 守护进程的来源与许可见顶层 NOTICE。
