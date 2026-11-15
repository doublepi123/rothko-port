# 验证记录与证据边界

记录日期：2026-11-15。均为一台中国版 Redmi K70 至尊版，不能据此
推导国际版 Xiaomi 14T Pro 或全部面板/指纹器件版本均兼容。

## 手机上的最新已验收组合

启动链摘要：

```text
3bf0f8ac7831d363a6c6941cc1749fdf75f1a5436adbfe4ab3266519f202de4a
```

| 部分 | 内容 | 验证级别 |
| --- | --- | --- |
| vendor 指纹 | spike02 Lineage AIDL HAL + 静态 rothko handler | 已刷写、分区回读、用户实测 |
| services/SystemUI | 去旧 FOD 实现，保留锁屏几何及惰性资源 | 已重建、签名、回读、真机启动及用户实测 |
| SystemUI RRO | pixel_pitch=57.0 | 已刷写，overlay 启用；用户确认图标正常 |
| Hey Google | global SCP + v36 组件，重录 Voice Match | 用户确认亮屏/息屏都能唤醒；重录后未补抓 DSP 日志 |
| 正式整理后的指纹模块 | hardware/xiaomi 补丁 + device udfps | 编译及链接检查通过，尚未替换手机 spike02 |

## 已捕获的运行证据

- spike02：framework `accept=14, reject=0`，两枚指纹保留，HAL death=0。
- 部分保留日志显示 `fod_press_status=1`、LHBM、HAL 成功认证，
  再由标准 BIOMETRIC 原因从 Dozing 唤醒；若干样本约 150–180 ms。
- 用户完成连续亮屏/息屏按压并报告正常。并非每次动作都保留原始日志，
  也未证明这些动作都触发了 `TOO_FAST`。
- 去 FOD 实现后用户确认亮屏/息屏解锁正常；随后图标异常通过 RRO 修复。
- 最新开机探测为 user、SELinux Enforcing，system_server/SystemUI/HAL
  在运行，两枚指纹存在，无当前开机崩溃记录。
- 通话、相机、振动在先前对应构建由用户确认；最近 RRO 刷写后没有
  对所有邻接功能重新做全面自动化回归。

原始 bugreport、唯一标识和个人数据留在私有工作区；本包只提供
经过脱敏的事实摘要。验证结果不是安全审计、CTS/VTS 认证或稳定性保证。

## 本轮整理的 CLI 证据

本轮不更改手机，不重新编译整个 ROM。实际验证包括：精确基线上的全部
活动补丁应用、错误基线/脏工作区/重复应用拒绝且各仓库 HEAD 不变、
离线 bundle 克隆、文件/许可/隐私扫描、XML/文档链接检查。
具体命令、结果和清理回执随本地交付的验证报告提供。
