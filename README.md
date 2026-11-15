# Redmi K70 Ultra / rothko — source preparation

这里整理中国版 Redmi K70 至尊版（2407FRK8EC、MT6989）的 LineageOS
23.2 / Android 16 移植。这是**实验性开源移植项目**，不是
LineageOS 官方设备或可直接刷入的发行版。

项目地址：https://github.com/doublepi123/rothko-port

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

## 单仓库布局

```text
rothko-port/
├── device/xiaomi/rothko/            # 设备树、指纹 handler、显示 RRO
├── vendor/xiaomi/rothko/            # 厂商输入清单和脚本，无镜像
├── patches/                        # 8 个上游项目的活动补丁
├── archive/legacy-fod/              # 旧 FOD 补丁，入口脚本不应用
├── docs/                           # 构建边界、验证和准入差距
└── tools/                          # 源码接入、补丁应用、主机镜像工具
```

克隆一次即可取得设备树、厂商整理脚本和补丁，不需要 submodule。
三份原仓库的提交与作者通过非压缩合并保留，见
[来源与历史](docs/SOURCE-HISTORY.md)。

```bash
git clone https://github.com/doublepi123/rothko-port.git
cd rothko-port
bash tools/install-source.sh /absolute/path/to/android
```

将本项目检出在 Android 源码树**外部**，再用接入脚本复制所需目录，
避免 Soong 同时扫描两份设备模块。已有目标目录不同会整体拒绝，
相同内容则保持原样。补丁应用和平台输入要求见
[构建说明](docs/BUILDING.md)；接入成功不代表整机已可构建。

## 当前状态

一台中国版设备上已经测试：亮屏/息屏指纹解锁、反复点按、
指纹图标、振动、通话、相机，以及重录 Voice Match 后的亮屏/息屏
Hey Google。详细证据级别见 [验证记录](docs/VALIDATION.md)。

截至记录时，测试设备的指纹二进制是 `spike02`，不是后来整理编译的正式模块；
二者不能混称同一个已刷产物。当前 services/SystemUI 没有旧 FOD
桥接实现，但保留锁屏几何调整和少量不被调用的常量/默认关闭资源，
所以也不能称为完全未修改的 Lineage 框架。

整机 `m` / OTA 流程尚未贯通，设备前置检查会明确拒绝当前不具备
发布证据的整机目标。不要把模块编译或补丁应用成功当作整机可复现。

本仓库不包含固件、Google APK、私钥或可刷 nightly。
目前没有启用每日 ROM 构建/自动发布工作流。
