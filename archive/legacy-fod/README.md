# 旧 FOD 实验归档

`complete-framework-fod.patch` 是整理前的完整 frameworks/base 补丁，
包含 Rust 守护进程配套的 FOD 桥接、按压租约、UI frame-commit 管线
和锁屏布局。保留其原始字节及作者，供查阅和恢复实验。

它不在 `patches/BASES.tsv` 中，`apply-patches.sh` 不会应用。
不要把它和当前活动的锁屏几何补丁一起应用。

旧 mfp-daemon-rs 的独立本地仓库和原工作区改动保持原状，
无需作为当前构建依赖同步。
