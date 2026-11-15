# 官方机型准备：尚未满足的条件

这里是工程差距记录，不是 LineageOS 的准入决定。
应以提交时的 [设备支持要求](https://github.com/LineageOS/charter/blob/main/device-support-requirements.md)
和 [提交说明](https://wiki.lineageos.org/submitting_device) 为准。

| 事项 | 现状 | 下一阶段的可验证结果 |
| --- | --- | --- |
| 指纹框架依赖 | 旧 FOD 桥接已不需要；仍有锁屏几何调整和兼容加载补丁 | 将通用/设备专用修改分别评审，验证共享库形态 |
| vendor 来源 | 仍依赖修改后的预编译镜像 | extract-utils 清单及可重建 vendor/odm，取消镜像修补依赖 |
| 内核与模块 | MiCode 发布了 rothko Android U 内核及部分 MTK 模块 | 按许可证和构建规则逐模块建立源码对应，确认可构建部分及缺口 |
| 发布证据 | 整机 preflight 仍拒绝缺失的证据 | VINTF、SELinux neverallow、链接命名空间、ABI、整机复现通过 |
| 恢复与升级 | 实验使用 OrangeFox | Lineage Recovery、Updater OTA、双槽固件流程实测 |
| 分支 | 当前基于 lineage-23.2 | 向上游确认受理分支，不能仅由默认分支推断必须迁移 |
| 硬件回归 | 目前为有限的一台设备验收 | FBE、NFC、GPS、录影/编解码、USB/MTP/共享网络等按 charter 完整验证 |
| 长期维护 | 尚未走官方提交 | 维护者设备、问题追踪、更新责任和提交署名准备 |

小米公开源码：

- [Xiaomi_Kernel_OpenSource / bsp-rothko-u-oss](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/bsp-rothko-u-oss)
- [MTK_kernel_modules / bsp-rothko-u-oss](https://github.com/MiCode/MTK_kernel_modules/tree/bsp-rothko-u-oss)
- [已提交的源码请求 #41191](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/issues/41191)

模块名与源文件名不能一一对应，仅按名字搜索不能证明某个模块一定缺失。
GitHub 递归树曾返回 truncated，因此不能据此作完整源码审计。
268 个 vendor 模块中 263 个声明 GPL-compatible license 是已测元数据；
`MODULE_LICENSE` 本身不替代完整法律判断，也不能证明厂商 GPL 义务范围。

GKI 可使用何种预编译内核、哪些模块必须源码构建、是否能接受例外，
需要结合完整来源和上游反馈判断。不要把此前粗略可行性分析写成
“已经确定有无法绕过的官方拒绝”。
