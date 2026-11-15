# Redmi K70 Ultra / rothko — source preparation

这里整理中国版 Redmi K70 至尊版（2407FRK8EC、MT6989）的 LineageOS
23.2 / Android 16 移植。当前是**本地源码准备包**，尚未发布，也不是
LineageOS 官方设备或可直接刷入的发行版。

目前采用 Lineage `hardware/xiaomi` AIDL 指纹 HAL 加设备侧
`UdfpsHandler`。旧 Rust 守护进程和 FOD 框架桥接保留作历史参考，
不再通过活动补丁入口安装。

## 从哪里看

| 文件 | 内容 |
| --- | --- |
| [INVENTORY.md](INVENTORY.md) | 仓库、补丁、来源和归档范围 |
| [docs/BUILDING.md](docs/BUILDING.md) | 精确基线、补丁应用、模块构建及整机缺口 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 真机证据、用户验收和验证限制 |
| [PORTING-NOTES.md](PORTING-NOTES.md) | 指纹、振动、硬件热词的原因与方案 |
| [docs/OFFICIAL-READINESS.md](docs/OFFICIAL-READINESS.md) | 申请官方支持前仍需解决的事项 |
| [NOTICE](NOTICE) | 许可、署名和专有输入边界 |

## 本地布局

```text
rothko-opensource/                   # 顶层文档、补丁和工具仓库
├── android_device_xiaomi_rothko/    # 独立设备树仓库
├── android_vendor_xiaomi_rothko/    # 独立厂商输入整理仓库，无镜像
├── patches/                        # 8 个上游项目的活动补丁
├── archive/legacy-fod/              # 旧 FOD 补丁，入口脚本不应用
├── mfp-daemon-rs/                   # 旧实现的独立历史仓库，不是当前依赖
├── local_manifests/                 # 未发布 fork 的清单模板
└── rothko-image-tools/              # 主机镜像工具，不连接手机
```

这几个独立仓库不是顶层的 submodule；只克隆顶层不会自动获得设备树。
本轮生成的离线交付目录包含顶层、设备树、厂商输入仓库各自的 bundle、
提交索引和 SHA256SUMS，按交付目录中的说明克隆。

## 当前状态

一台中国版设备上已经测试：亮屏/息屏指纹解锁、反复点按、
指纹图标、振动、通话、相机，以及重录 Voice Match 后的亮屏/息屏
Hey Google。详细证据级别见 [验证记录](docs/VALIDATION.md)。

手机当前的指纹二进制仍是 `spike02`，不是后来整理编译的正式模块；
二者不能混称同一个已刷产物。当前 services/SystemUI 没有旧 FOD
桥接实现，但保留锁屏几何调整和少量不被调用的常量/默认关闭资源，
所以也不能称为完全未修改的 Lineage 框架。

整机 `m` / OTA 流程尚未贯通，设备前置检查会明确拒绝当前不具备
发布证据的整机目标。不要把模块编译或补丁应用成功当作整机可复现。

本轮只整理本地内容，不包含刷机、推送或新硬件功能变更。
