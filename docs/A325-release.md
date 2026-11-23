# PvZ2-Unline:Aster A325 正式版

**不推荐 ARM64，优先使用 ARM32。** ARM32 已在 WSA 验证。ARM64 使用相同的游戏引擎，尚未在设备上验收。

- 开启「社交版拓展内容」后，三星关卡须领取对应世界的三星罐头才能选星。海盗港湾的奖励在第 10 天，领奖前点已打过的第 7 天也会直接进入无星主线。单星关卡沿用原有规则。
- 世界地图换上好友图标并调整顶栏、两侧和底部按钮的对齐。
- 方形头像裁为圆形并按角色配色。头像选择页新增 6 个《植物大战僵尸2》国际版竞技场头像。新版本可显示导出的新头像，旧版本仍可读取玩家资料。

## 构建

两份完整 APK 从 A321 正式包保留三个资源分卷。ARM32 使用已验证的 A325 引擎和应用代码。ARM64 同步引擎、动态资源和好友数据逻辑，保留该架构的启动器。

```powershell
python scripts/build_aster_release_a325.py --test D:/Aster-builds/A325/PvZ2-Unline-Aster-A325-ARM32-WSA-existing-data.apk --base D:/Aster-builds/A321/release --output D:/Aster-builds/A325/release --sdk D:/Android/Sdk --signing D:/Signing/aster.json
```

构建脚本核对资源分卷、签名、ZIP 对齐和包内容。完整包的全新安装尚未在设备上验收。
