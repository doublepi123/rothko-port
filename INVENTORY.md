# 内容清单

## 当前单仓库组成

| 名称 | 用途 | 许可/来源 |
| --- | --- | --- |
| `rothko-port` 顶层 | 文档、活动补丁、接入脚本、镜像工具 | 原创整理内容 Apache-2.0；补丁保留来源 |
| `device/xiaomi/rothko` | 设备配置、RRO、IMS 引入、振动 alias、UDFPS handler | 依文件头与 LICENSE |
| `vendor/xiaomi/rothko` | 固件输入清单、校验与整理脚本 | 依文件头与 LICENSE，不含专有镜像 |

旧 `mfp-daemon-rs` 不纳入当前源码树，上游为
[hoshikv/mfp-daemon-rs](https://github.com/hoshikv/mfp-daemon-rs)，基于
`2f42d751554db496b055ebb64e3e425acffccf04`。它保留自己的 LICENSE、
NOTICE 和历史保留在原本地工作区，不是当前运行方案或构建依赖。

## 活动补丁

精确 40 位基线和上游地址以 [BASES.tsv](patches/BASES.tsv) 为准。

| 项目 | 补丁数 | 当前内容 |
| --- | ---: | --- |
| frameworks/base | 3 | 锁屏几何和诊断；独立 UI 避让；可按设备选择充电进度估算；无旧 FOD 会话或触摸实现 |
| frameworks/native | 1 | vibratorfeature 实例回退、BLAST 初始化竞态修复 |
| packages/apps/Settings | 1 | 指纹录入界面调整 |
| packages/apps/StorageManager | 1 | 清理页根布局消费窗口边距，避免列表被标题栏遮挡 |
| packages/apps/CarrierConfig | 1 | 语音能力快照及受权限约束的 dump |
| bootable/recovery | 1 | 当前恢复环境的正常退出桥接与加载约束 |
| system/sepolicy | 4 | CIL 合并、zygote 原型开关、受检查的兼容调整 |
| external/perfetto | 1 | 唤醒锁追踪不阻塞 |
| hardware/xiaomi | 3 | 无变体后缀的旧 HAL 加载；预编译 vendor 的静态 handler/配置桥接；指纹请求开始与结束时的高亮门控 |
| build/soong | 2 | 传递经过校验的 GOMEMLIMIT；可选本地 JVM 高内存任务池 |
| build/make | 1 | target-files 显式依赖预编译 init_boot 的安装目标及许可元数据 |

共 11 个项目、19 个补丁。`tools/apply-patches.sh` 只读取这个活动索引。
上游已合并与否、是否适合官方准入需要分别评审，不能据此视为获上游认可。

## 已归档内容

[archive/legacy-fod](archive/legacy-fod/README.md) 保存完整旧
frameworks/base FOD 补丁。`archive/multi-repo-manifest.xml` 是旧多仓库
发布方案的清单模板，不用于当前构建。不重写原分支，不删除原源码工作区，
不自动应用归档补丁。`build/soong` 加入经过验证的 Go 堆预算传递和可选 JVM 并发限制补丁；
其他本地 Soong/Blueprint 调优不在活动索引中。

## 不包含的输入

以下内容需要从合法取得的固件自行提取，或另行核实再分发权限；
本包不作一概可再分发的法律判断。

| 输入 | 来源/状态 |
| --- | --- |
| boot/init_boot/vendor_boot/dtbo/vendor/odm/dlkm 镜像 | CN `OS3.0.308.0.WNNCNXM`；源哈希在厂商树清单 |
| ImsService.apk | 同版本 system_ext，见设备树 ims/prebuilt/README.md；实验导入副本与原 APK 差异尚待审计 |
| Google 热词 SCP | global `OS3.0.303.0.WNNMIXM` |
| v36 热词录入 APK、common.util.jar | 同一 global 固件的 product/system_ext；不包含声音模型和个人录音 |
| GApps | 用户自行选择并核实使用权限 |
| AVB/platform 私钥 | 自行生成，不包含开发者密钥 |

原始 bugreport、手机数据、设备唯一标识、实验系统镜像、临时构建缓存
均不纳入交付包。内部日志路径只出现在本轮私有证据目录。
