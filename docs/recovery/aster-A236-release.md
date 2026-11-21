# Aster A236 构建与验证

A236 的应用 ID 为 `com.pvz2unline.aster`，版本号为 `1.7.5-Unline-Aster-A236`（1236）。优先使用经 WSA 用户验收的 ARM32。ARM64 为实验包，未运行验收，不推荐使用。 [A236 正式版与更新记录](https://github.com/EndiVee233/PvZ2-Unline-Aster/releases/tag/v1.7.5-v236-aster-dual-arch)

## 构建输入

- `--base` 指定包含 `PvZ2-Unline-Aster-A232-ARM32.apk` 和 `PvZ2-Unline-Aster-A232-ARM64.apk` 的目录。
- `--stock` 指定包含 `PvZ2-Unline-Aster-A227-ARM32.apk` 的目录。构建读取其中的 A227 引擎，再编译并应用地图资源、自动拾取和活动无尽续打补丁。
- 构建环境使用 Windows、Android SDK Build-Tools 34.0.0、NDK 27.0.12077973、JDK 和 Python。将 Apktool 放在仓库旁的 `tools/apktool.jar`，并将 pyvz2 的 `OBBEdit/libraries` 加入 `PYTHONPATH`。Python 依赖包括 `pyelftools`、`keystone-engine` 和 `py3rijndael`。
- `--signing` 指定自己的本地签名配置，字段为 `keystore`、`alias` 和 `password`。将该配置和密钥保存在仓库外。

```powershell
python scripts/build_aster_festival_chooser.py `
  --base path/to/A232 --stock path/to/A227 --output path/to/A236 `
  --sdk path/to/android-sdk --ndk path/to/android-sdk/ndk/27.0.12077973 `
  --signing path/to/local-signing.json
```

该命令使用已有的 A227 和 A232 APK 作为输入。源码仓库提供补丁与构建脚本，游戏数据和签名材料需自行准备。

## 验证

从发布源码和上述输入重新生成了 ARM32 的引擎、活动关卡资源、解码计划、Manifest 和启动 DEX。五项均与已发布 APK 中的文件逐字节一致。
