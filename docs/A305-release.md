# PvZ2-Unline:Aster A305 正式版

**不推荐 ARM64，优先使用 ARM32。** ARM32 在 WSA 以同一引擎和应用代码验收。ARM64 同步使用该引擎，未做设备验收。

- 未来世界小游戏的阳光炸弹只会在直接点击时引爆。它变成普通阳光后，自动拾取、A 键和鼠标滑过均可收集。
- PVP 的僵尸能量豆自掉落起由系统接管，防守植物沿用原有的大招流程。签到使用循环日历，PVP 第三区和商铺侦察随区域解锁更新。
- 设置里可启用「社交版拓展内容」，默认关闭。已支持十个世界的星级选择与计时、好友成绩与个人排名、阵型及选卡预览、友情阳光和借用植物。
- 用户主页提供头像、出借植物、玩家数据导出和礼包码入口。外置存档可在设置中导出备份和恢复。游戏内制作人名单标注用户界面素材来自《植物大战僵尸2》中文版 4.2.8。

A305 的阳光炸弹状态转换和三种拾取方式已通过 WSA 用户验收。PVP 能量豆在 A304 通过 WSA 用户验收，A305 继续使用同一接管逻辑并通过回归检查。完整单 APK 含三段资源，已验证签名与包内容。完整包的全新安装仍待设备验收。

[社交版移植记录](tencent-social-port-plan.md) · [外置存档说明](aster-save-backup.md)

## 构建

A305 的可运行测试包由 A303 ARM32 测试包构建。正式包使用同一个引擎及通过验收的共享资源，从 A250 完整底包保留三个资源分卷。ARM64 保留 A250 的宿主和架构专用 DEX，在 ARM64 的入口代码上重新接入新版 Java 钩子。

环境需要 Java 17、Android SDK Platform 34 和 Build Tools 34.0.0、NDK 27、同级 `tools/apktool.jar`、`pyelftools`、`keystone-engine` 和 `pyvz2rton`。验证使用 `unicorn`。签名配置和测试存档为本地输入。

```powershell
python scripts/build_aster_pickup_access.py --base D:/Aster-builds/A303/PvZ2-Unline-Aster-A303-ARM32-WSA-existing-data.apk --output D:/Aster-builds/A305 --sdk D:/Android/Sdk --ndk D:/Android/Sdk/ndk/27.0.12077973 --signing D:/Signing/aster.json
python scripts/check_aster_pickup_access.py D:/Aster-builds/A305/libSrc.so
python scripts/build_aster_release_a305.py --test D:/Aster-builds/A305/PvZ2-Unline-Aster-A305-ARM32-WSA-existing-data.apk --seed D:/Aster-builds/A303/PvZ2-Unline-Aster-A303-ARM32-WSA-existing-data.apk --base D:/Aster-builds/A250 --output D:/Aster-builds/A305/release --sdk D:/Android/Sdk --ndk D:/Android/Sdk/ndk/27.0.12077973 --signing D:/Signing/aster.json
```

A302 的玩法和资源由 `build_aster_adventure_records.py` 生成，输入包括 A250 完整双架构底包、社交图集 ZIP 和经授权的中文版 4.2.8 本地 APK。A303 由 `build_aster_p0.py` 在 A302 的 WSA 测试包上加入签到与 PVP 更新。
