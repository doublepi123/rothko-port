# 使用与构建边界

## 获取与接入

本仓库已经包含设备树和厂商输入脚本。先把它检出到 Android 源码树外：

```bash
git clone https://github.com/doublepi123/rothko-port.git
cd rothko-port
bash tools/install-source.sh /absolute/path/to/android
```

接入目标必须包含 `build/envsetup.sh`。脚本先检查两个目标目录，
不同内容、普通文件或符号链接目标均拒绝，不覆盖用户修改。
相同目录再次调用不会改动；缺失的目录按本仓库内容复制。
跨两个目录的安装不是磁盘故障下的原子事务，不要并发修改同一目标。
厂商脚本仍依赖的外部输入布局并不会由这个接入步骤补齐。

原仓库历史已经合并在本仓库，不需要分别 clone 或初始化子仓库。
历史 mfp-daemon-rs 不需要复制到当前构建。

## 上游与补丁

1. 同步 Lineage 23.2 的源码。不能只追踪浮动分支就声称可复现：
   `patches/BASES.tsv` 列出的十一个改动仓库必须位于指定基线。
   [固定清单](../tools/manifests/platform.xml) 冻结 1,165 个项目，包含补充的
   `hardware/xiaomi`，其余项目沿用既有 Lineage/AOSP 同步基线。
2. 可用 [本地缓存准备流程](CLEAN-BUILD.md) 建立独立检出，避免重拉源码。
3. 在每个项目的**干净独立分支**上 checkout 对应基线。
4. 设置自己的 Git committer 身份后执行：

```bash
bash tools/apply-patches.sh /absolute/path/to/android
```

入口会先检查全部十一个仓库的基线、干净状态、committer 身份和补丁能否
应用，再逐仓库 `git am`。基线不符、脏目录或重复应用会在第一次提交前
拒绝；它不会自动 reset 或 stash 用户内容。应用中遭遇磁盘错误等情况
并不构成跨仓库原子事务，需按输出定位 `git am` 状态后人工处理。

原多仓库 `local_manifest` 模板已移到 `archive/multi-repo-manifest.xml`，
因为这里没有发布独立的上游 fork。当前流程是单仓库接入加补丁应用，
不要把归档模板复制进 `.repo/local_manifests`。

## 当前可构建目标

在已有平台依赖、合法取得并校验的固件输入和 device/vendor 集成环境中，
原验证使用：

```bash
export OUT_DIR=out-rothko
source build/envsetup.sh
lunch lineage_rothko-bp4a-user
build/soong/soong_ui.bash --make-mode --soong-only -j8 \
  android.hardware.biometrics.fingerprint-service.rothko-prebuilt-vendor \
  libudfpshandler
```

这两个目标已在原工作区编译成功。此命令只构建模块，不生成能刷入的
完整系统。`--soong-only` 不会使未具备证据的整机目标变成发布就绪。
前置检查脚本维持原样；本轮没有降低发布门槛。

当前 vendor 是预编译镜像，`fingerprint.mk` 未被引入。其属性/共享库
形态面向未来源码构建 vendor，还需处理旧服务、VINTF、SELinux、
模板目录兼容和实际加载验证。现在通过主机工具替换 mfp-daemon 的
兼容二进制，之后必须正确重建哈希树、FEC 和 vbmeta 链。

## 尚未贯通的整机步骤

- proprietary 提取流程仍依赖内部固件/证据布局，尚不是独立 extract-utils 流程。
- ImsService 实验导入副本与原固件 APK 的差别需要审计。
- source-built vendor/odm、指纹组件安装、完整 SELinux/VINTF/ABI 证据未闭环。
- SCP、热词 APK/库与 VoWMic 的后处理还未纳入正式构建。
- 当前实验包含开发密钥签名；不要使用或索取开发者私钥，应自备密钥。
- 完整 OTA、Updater、双槽固件一致性和 Lineage Recovery 未按官方路径验收。

因此这里不提供“`lunch && m` 即可复现当前手机”的承诺。
