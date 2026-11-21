# PvZ2-Unline:Aster A272 预发布

**不推荐 ARM64，优先使用 ARM32。** ARM32 已在 WSA 验收本版的星级挑战、结算显示和埃及旧无尽续层。ARM64 同步构建，待设备验收。

- 神秘埃及第 1、2 天新增原生选关页。可选无星、第一星、第二星和第三星，沿用对应的原生过关条件。完成本关主线或领取埃及第 11 天的三星罐头可开放星级挑战。
- 选关页按星级列出离线好友成绩和个人最佳。选择好友后，可在该关棋盘上查看原格位和阶数的植物。阵型预览沿用 PVP 布防的动画和原生返回按钮。
- 跳档挑战时，开场和结算按实际获得状态逐颗显示星星。集齐三颗才显示「你获得了所有星星！」。
- 修复埃及旧无尽续层进战后植物停摆。普通攻击、阳光生产和能量豆大招恢复更新。

WSA 验收使用 ARM32 的本地资源测试包。完整包的全新安装、埃及第 11 天首胜领取罐头的实机流程仍待验收。罐头解锁和账号隔离已通过 ARM 模拟检查。 [移植记录](tencent-social-port-plan.md)

## 构建

构建需要 A250 的 ARM32 和 ARM64 完整 APK、Java 17、Android SDK Platform 34、Build Tools 34.0.0、NDK 27、Apktool 及本地签名配置。Python 用到 `pyelftools`、`keystone-engine` 和用于回归检查的 `unicorn`。将 Apktool 放到源码目录同级的 `tools/apktool.jar`，按本机位置替换下列示例路径。

```powershell
python scripts/build_aster_adventure_records.py --base "D:/Aster-builds/A250" --output "D:/Aster-builds/A272" --sdk "D:/Android/Sdk" --ndk "D:/Android/Sdk/ndk/27.0.12077973" --signing "D:/Signing/aster.json" --social-levels
python scripts/check_aster_adventure_records.py "D:/Aster-builds/A272" --social-levels
```

发布附件为两份带完整资源的 APK。源码通过 A272 标签下载。 [A272 发布页](https://github.com/EndiVee233/PvZ2-Unline-Aster/releases/tag/A272)
