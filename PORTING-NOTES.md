# 移植笔记

## 指纹：当前方案

使用 Lineage `hardware/xiaomi` AIDL 指纹服务（IMPL_V2），加载
`fingerprint.goodix_fod.so`，设备侧 `udfps/RothkoUdfpsHandler.cpp`
负责局部高亮和按压。官方源码的 `hw_get_module_by_class` 未找到
不带变体后缀的库；当前分支增加直接加载该文件的兼容路径。
这只是在本机整理成独立提交，还未提交上游。

handler 收到按压后发 extCmd 1，使用 mi_display 的 local-HBM
ioctl `0x400c440e`，显示事件 type 2 表示可采图后发 extCmd 10。
释放时结束高亮与按压。息屏时通过 TouchFeature mode 10 和
`fod_press_status` 获得接触；Goodix 匹配成功后，框架按标准
生物识别路径唤醒。当前实验未添加新的 AOSP UDFPS 传感器。

对照参考：

- [Lineage peridot UdfpsHandler](https://github.com/LineageOS/android_device_xiaomi_peridot)
- [Lineage mt6895-common](https://github.com/LineageOS/android_device_xiaomi_mt6895-common)
- [Lineage hardware/xiaomi](https://github.com/LineageOS/android_hardware_xiaomi)

`fingerprint.mk` 是将来构建 vendor 时的集成片段，当前不被
device.mk 引入。当前预编译 vendor 使用静态链接的兼容构建目标，
其正式整理版本仅编译验证过，手机仍运行 spike02 版本。
请勿把共享库构建成功说成共享库形态已经在手机加载过。

传感器中心 `(610,2444)`、半径 `105`、sensor ID `5` 延续现有
数据。实验保持模板路径 `/data/vendor_de/<user>/fpdata`。
去掉末尾斜杠是本次迁移采用的兼容选择，没有用 A/B 实验证明
斜杠本身必然造成模板丢失。

## 指纹图标

原版 SystemUI 通过 `udfps_icon_size / pixel_pitch` 计算尺寸；
默认 `pixel_pitch=-1` 对本机不合适。设备 SystemUI 几何 RRO
配置 `57.0` 微米（`25400 / 445.614 dpi`），用户已确认显示恢复正常。
无需恢复旧的框架图标 padding 兜底。

## 振动

原厂服务暴露 `IVibrator/vibratorfeature`。当前方案保留设备树的
alias 和 frameworks/native 的实例回退，真机振动已确认。
它们是否可以进一步合并成单一路径需要独立验证，本轮不删除。

## Hey Google 硬件热词

CN SCP 对外报告默认引擎；global 303 SCP 可提供 Google 引擎。
全局固件的 TFLite 引擎需要匹配的 v36 录入 APK、common.util.jar
和 `com.mediatek.hardware.vow.gva.tflite` 特性。旧 v35 的 mmap 模型
在早期试验中触发 SCP 崩溃。

`VoWMicSetting_AudioParam.xml` 的 `dual_ch_transfer` 设为 global
值 0；单独修改它并未解决崩溃。SCP、模型、APK 和共享库匹配才是
该轮实验的关键。system_ext 替换包时还需考虑 PackageManager 缓存。

最近一次故障的现场为：DSP 枚举正常、v36 包和权限存在，但 enrolled
model 为空、GSA 没有 detector。**无法从已保留日志判断是谁、何时、
为什么清除了模型，也不能证明它与框架替换无关。**
用户重新训练 Voice Match 后确认亮屏和息屏都恢复。
重录后的 DSP LOAD/START 未捕获，验证边界见验证记录。

硬件热词依赖的专有组件不包含在本包里，也不与官方设备申请绑定。
