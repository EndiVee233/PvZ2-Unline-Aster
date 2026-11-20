# A197 构建与验证

A197 的 ARM32 和 ARM64 APK 保存在 [GitHub Releases](https://github.com/EndiVee233/PvZ2-Unline-Aster/releases/latest)。普通 Android 和模拟器优先选 ARM32。两个包使用同一份 ARM32 游戏逻辑。ARM64 包另有执行这份逻辑的 AArch64 宿主。

## 修复范围

- A191–A192 调整了 PVP 侦察奖励、费用、教程药剂扣费和战报。普通邻居显示三星可得奖励，邪恶戴夫按 30 星币进攻，以六次胜利为一轮。
- A193–A194 调整首次进入 PVP 时的视频配乐，并在设置里按玩家身份管理可选测试存档。A195 处理 MuMu 安卓 12 首次加载 ARM32 原生库的失败。
- A196 修复连续教学进入前院 4 时提前释放仍在使用的资源组，给五条教学信息恢复五秒计时，并调整 ARM64 的 OpenSL ES 队列。
- A197 修复 ARM64 上 Wwise 加载音库时重复使用信号量地址的竞态。ARM32 沿用 A196 引擎和资源，更新包版本号。MuMu 安卓 12 上已通过连续进入前院 4 的画面、音乐和种植音效检查。ARM64 另完成六次冷启动音库检查。不同手机的音频驱动仍需实机反馈。

## 从公开 A197 重编 ARM64 宿主

以下命令在 Windows PowerShell 的仓库根目录运行。需要 Git、CMake 3.22、Ninja、Android NDK 27.0.12077973、Android SDK Build Tools 34.0.0、JDK 17、Python 3.10 或更高版本，以及 Apktool 2.10.0 的 JAR。将环境变量 `ANDROID_HOME` 和 `APKTOOL_JAR` 指向各自安装位置。`$apk` 是自己持有的完整 A197 ARM64 APK。

```powershell
$root = (Get-Location).Path
$build = Join-Path (Split-Path $root) 'aster-a197-build'
New-Item -ItemType Directory -Force $build | Out-Null
$apk = (Resolve-Path 'PvZ2-Unline-Aster-A197-ARM64.apk').Path
$ndk = Join-Path $env:ANDROID_HOME 'ndk/27.0.12077973'
$cmake = Join-Path $env:ANDROID_HOME 'cmake/3.22.1/bin/cmake.exe'
$ninja = Join-Path $env:ANDROID_HOME 'cmake/3.22.1/bin/ninja.exe'
$bridge = Join-Path $build 'arm64-bridge-a7'
$astc = Join-Path $build 'astc-codec'
git clone https://github.com/phys-winner/arm64-bridge-a7.git $bridge
git -C $bridge checkout --detach 9a963e911c2f8c8051a7bc00ae48ff380306d14c
git -C $bridge submodule update --init --recursive --depth 1 --jobs 8
git clone https://github.com/google/astc-codec.git $astc
git -C $astc checkout --detach 9757befb64db6662aad45de09ca87cd6f599ac02
python -m pip install pyelftools
python scripts/extract_aster_jni_contract.py $apk $env:APKTOOL_JAR "$build/contract"
& $cmake -S src/arm64-probe -B "$build/native" -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$ninja" "-DCMAKE_TOOLCHAIN_FILE=$ndk/build/cmake/android.toolchain.cmake" `
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-24 -DANDROID_STL=c++_static `
    -DCMAKE_BUILD_TYPE=Release "-DA7_BRIDGE_SOURCE=$bridge/arm64_bridge" `
    "-DASTER_ASTC_SOURCE=$astc" "-DASTER_CONTRACT_DIR=$build/contract" `
    -DASTER_INCLUDE_COMPANIONS=ON -DASTER_GAME_RUNTIME=ON -DASTER_RUNTIME_DIAGNOSTICS=OFF `
    -DASPHALT7_FINAL_SILENT=ON -DASPHALT7_FAILURE_TELEMETRY=ON
& $cmake --build "$build/native" --target Android --parallel 6
& "$ndk/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe" --strip-debug `
    -o "$build/libSrc.so" "$build/native/a7/libSrc.so"
```

生成的 JNI 头包含 10 个类和 36 个方法。发布前在独立目录按上述配置重编宿主，使用发布构建留存的第三方源码进行对照。两个产物各 7,181,704 字节，只有 ELF build ID 的 20 字节有差异。第三方依赖的全新下载以及各工具补丁版本可能改变产物哈希。

打包脚本需要本地签名配置 JSON，字段为 `keystore`、`alias`、`password`。路径指向自己的密钥库，密码用于该密钥库及其别名。将配置文件路径放入环境变量 `ASTER_SIGNING_CONFIG`。从公开 APK 重打包的命令如下。

```powershell
python scripts/build_aster_arm64_audio_a197.py --from-release $apk "$build/libSrc.so" `
    "$build/A197-ARM64-local.apk" $env:ANDROID_HOME $env:ASTER_SIGNING_CONFIG
```

脚本验证底包引擎、宿主、资源分片、签名及 ZIP 对齐。自签名 APK 与正式版的签名不同，用于独立测试安装。

## 从 A190 追溯共享游戏逻辑

`scripts/build_aster_pvp_review_fixes.py --help` 列出复编 A195 引擎及迁移 DEX 的参数。除正式 A190 APK 外，还需要 A187 引擎、保留符号的 A187 `offline.elf` 与 `offline.o`，以及 A190 生成的 PVP 头文件和校验 JSON。这些历史中间产物未随源码分发。需要 Python 的 `py3rijndael`、`keystone-engine`、`pyelftools`。在具备这些输入时，已验证生成引擎和 `classes9.dex` 与 A195 一致。

`scripts/build_aster_tutorial_a196.py --help` 从 A195 双架构底包生成 A196。ARM64 另需对应 A196 的 OpenSL ES 宿主。已有 A196 ARM32 APK 可直接制作 A197：

```powershell
python scripts/build_aster_arm64_audio_a197.py --arm32 PvZ2-Unline-Aster-A196-ARM32.apk `
    "$build/A197-ARM32-local.apk" $env:ANDROID_HOME $env:ASTER_SIGNING_CONFIG
```

## 回归检查

- `scripts/check_aster_tutorial_a196.py <A195包目录> <A196包目录>` 需要 `unicorn` 和 `pyelftools`，检查两端的共享引擎、三个教学入口、音乐选择和信息计时。
- `src/arm64-probe/tests/semaphore/run.py --help` 给出使用 Android 测试设备运行原版及修复信号量代码的参数。未修改的代码来自 A7 的 `src/thunks_libc.cpp`，修复版本由 CMake 写入 `native/aster_audit_libc.cpp`。
- `scripts/check_aster_arm64_audio.py --help` 可在独立测试设备上重复冷启动，检查 PCM 帧与欠载。具体音乐及落种音效仍须进入教程复验。
