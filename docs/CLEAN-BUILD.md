# 使用本地源码缓存进行干净构建

本流程的目标是从独立源码检出、空输出目录及新生成的开发证书，构建完整设备镜像
和 `target-files`。2026-11-16 的从空输出构建曾因 WebView 仍是 Git LFS 指针而失败；
该输入准备问题已修复，原失败检查重跑通过。续编译又发现 target-files 缺少
预编译 init_boot 安装依赖，相关补丁已加入活动索引，正常构建图和镜像复制已验证；
完整打包仍待完成。
完整的空输出构建尚未通过最终验收，最终结果需要实际退出码与产物校验记录。

## 准备源码

准备工具要求主机已有 `git-lfs`。它读取固定提交中的 `filter=lfs` 属性，
先校验本地 LFS 对象缓存或内容匹配的参考工作区文件，再创建目标检出。
WebView 的 APK 属于这类输入；只有 Git 提交对象而缺少 LFS 实体并不足以构建。

[platform.xml](../tools/manifests/platform.xml) 固定 1,165 个 Lineage/AOSP 项目，
包含补充的 `hardware/xiaomi`。补丁基线由 [BASES.tsv](../patches/BASES.tsv) 约束。
现有工作区可以有项目修改，因为准备工具只读取其 Git 对象，不复制这些修改。
缓存中的 repo 工具本身需要保持干净。

```bash
python3 tools/prepare-source.py \
  --reference /absolute/path/to/existing/android \
  --destination /absolute/path/to/new/android
bash tools/install-source.sh /absolute/path/to/new/android
bash tools/apply-patches.sh /absolute/path/to/new/android
```

目标目录必须不存在。工具先检查所有固定提交是否在本地，然后创建独立 repo
元数据和工作目录，通过 Git alternates 复用不可变对象，运行 `repo sync --local-only`。
缺少 Git 或 LFS 对象会在创建目标目录前报错，不自动切换为联网同步；
Git 网络协议及 lazy fetch 均被禁止，LFS smudge 下载也被显式关闭。
检出完成后，只将经过尺寸与 SHA-256 校验的本地 LFS 实体独立复制到对应指针位置。
没有声明 `filter=lfs` 的普通源文件即使内容像指针，也保持原样。
工作目录文件、旧 `out`、编译缓存和私钥不会被复制。

保留原对象缓存，直到构建和归档结束；本流程没有执行 `git gc` 或清理原工作区。
不必再次下载整套源码。若更换基线，应先单独核实所缺对象和所需下载量。

本地 LFS 边界可用真实临时 Git 仓库离线重跑：

```bash
python3 -B -m unittest discover -s tests -p test_source_lfs.py -v
```

## 准备固件输入

将九个固定原厂镜像放入一个本地目录：`boot.img`、`init_boot.img`、
`vendor_boot.img`、`dtbo.img`、`vendor.img`、`odm.img`、`system_dlkm.img`、
`vendor_dlkm.img`、`odm_dlkm.img`。尺寸、哈希和机型由厂商树清单约束。

本版本还显式需要两份固定的 fstab 派生输入：`vendor.img` 和 `vendor_boot.img`。
哈希及历史配方证据见厂商树的 `derived-source-manifest.json`、`derived-manifest.json`
和 `evidence/`。准备工具把它们作为已知哈希的预编译输入，不声称重新生成了它们；
当前仓库尚未包含完整的 stock-to-derived 再生成流程。

```bash
python3 tools/prepare-inputs.py \
  --source-root /absolute/path/to/new/android \
  --stock-images /absolute/path/to/stock-images \
  --derived-images /absolute/path/to/derived-images \
  --payload-manifest /absolute/path/to/payload_manifest.bin \
  --ims-apk /absolute/path/to/stock/ImsService.apk
```

这一步只读取本地输入：先核对全部文件，再复制到独立源码树并生成暂存记录。
不依赖原调查目录中的父级日志，不下载固件，也不访问手机。IMS 使用文档所列
原始 APK 哈希，交给 Soong 正常处理 JNI/dex 和重新签名。

## 预编译 init_boot 的打包依赖

原始 init_boot 输入存在时，`target-files-package` 仍可能在复制输出目录中的
`init_boot.img` 时失败：上游已定义预编译镜像的安装规则，但 target-files 的
先决依赖没有引用这个目标。仅构建 target-files 时，Ninja 不会执行该复制规则。

`build/make` 的活动补丁补齐镜像目标及容器许可依赖，继续使用原安装规则，
保持镜像内容、签名和其他打包检查。补丁已在固定提交上通过独立 `git am`；
正常构建已生成正确依赖并复制出与原始输入完全一致的镜像；完整打包和最终空输出
构建仍待完成。

## A/B 镜像清单一致性

当前离线配置明确关闭 AVB 镜像签名，只构建三个框架分区并暂存九个固定镜像。
A/B 清单应引用这十二个实际产物；此前额外列出的三个 vbmeta 分区没有对应输出，
会被正常打包检查拒绝。配置生成器现在提前检查清单与构建/暂存计划完整一致，
同时拒绝重复、缺失、无来源的分区和隐式启用 AVB 签名。

```bash
python3 -B -m unittest discover -s tests -p test_partition_plan.py -v
python3 -B device/xiaomi/rothko/config/generate_device_config.py --check
```

五个生成器用例及七个构建准入用例通过；正常 A/B 镜像完整性、VINTF、签名和
最终打包检查仍需由实际构建完成。镜像计划调整不会授权 OTA 发布或设备刷写。

## 开发构建与发布检查

为 `vendor/xiaomi/rothko/keys/` 生成全新的开发证书和未加密 DER `.pk8` 私钥；
至少包含 `releasekey`、`platform`、`shared`、`media`、`networkstack`、`sdk_sandbox`、
`bluetooth`、`nfc`，每组配套 `.x509.pem`。目录已被 Git 忽略。不得复制开发者现有私钥。
这些证书用于开发应用签名，不代表 OEM 签名，也不改变原厂预编译镜像的认证来源。

```bash
bash tools/generate-development-keys.sh /absolute/path/to/new/android/vendor/xiaomi/rothko/keys
```

```bash
export OUT_DIR=out-clean
export ROTHKO_BUILD_PURPOSE=development
export GOMEMLIMIT=22GiB
export USE_RBE=false USE_REWRAPPER=false USE_REMOTEEXEC=false USE_CCACHE=0
export NINJA_HIGHMEM_NUM_JOBS=1
export SOONG_JAVA_HIGHMEM_POOL=true
source build/envsetup.sh
lunch lineage_rothko-bp4a-user
build/soong/soong_ui.bash --make-mode -j16 target-files-package check_target_files_vintf
```

运行前应确认 `out-clean` 不存在。外层构建服务使用 16 CPU、28 GiB 内存软限、
32 GiB 硬限、2 GiB swap 和 `OOMPolicy=stop`；Go 堆限制另行传入 Soong 构建图进程。
`SOONG_JAVA_HIGHMEM_POOL=true` 将 Soong 生成的本地 Java/Kotlin、turbine、D8/R8、签名、lint 和
文档生成任务放入同一 `highmem_pool`，深度由 `NINJA_HIGHMEM_NUM_JOBS=1` 控制；
原生任务仍按 `-j16` 调度。不开启此开关时沿用上游规则，远程构建保持原调度。
仅设置池深度不能限制普通 JVM 编译，可能因持续内存回收压力触发 systemd-oomd。
本次运行还通过系统服务限制外网地址族，防止远程编译或隐式下载消耗流量。

`development` 只让明确的镜像和 target-files 编译目标使用构建前输入检查。
设备型号、固定输入完整性、分区预算和编译器/VINTF/SELinux 的正常规则继续生效。
构建后的兼容性、镜像内容、签名和打包结果必须另行检查。
`otapackage`、`bacon`、混合发布目标及默认发布入口仍走原发布检查，
`release_readiness.ready` 和 `hardware_release_ready` 没有改为 true。

`check_target_files_vintf` 是与镜像一起构建的主机验证工具，会生成所需的
`checkvintf` 和 `apexd_host`。编译结束后需用实际工具检查 target-files，记录兼容、
不兼容或跳过的真实结果。ZIP CRC、固定预编译镜像哈希、实际镜像文件、构建属性和
应用签名另行校验；签名工具使用固定 JDK 与 `prebuilts/sdk/tools/linux/lib/apksigner.jar`。

本流程当前保持既有 AVB 构建配置；生成镜像与 target-files 是离线开发产物，
不能据此宣布 OTA 发布、手机可刷写、官方准入或设备运行验收完成。
