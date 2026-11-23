# PvZ2-Unline:Aster A321 正式版

**不推荐 ARM64，优先使用 ARM32。** ARM32 的选关、好友阵型和返回地图修复已在 WSA 验证。ARM64 使用同一游戏引擎，尚未做设备验收。

- 好友列表按存档保存，最多添加 6 位好友。可从 GitHub 获取玩家资料，并在关卡成绩中查看好友阵型和选卡。
- 修复选卡后返回地图，以及查看好友阵型时可能出现的两处闪退。星级结算的「下一颗星」会进入尚未取得的挑战。
- 月度签到从当月第一份奖励开始按序领取。补签每次消耗 10 钻石，已领奖励以绿色对勾标记。
- PVP 实验室入口显示剩余时间最长的升级。咖啡店、热狗店和商店在解锁街区分布，各自使用对应地形。
- PVP 新增镜像练习屋，可进攻自己的基地阵型。练习免出击费，不发奖励，也不扣除僵尸库存。

## 构建

两个正式包从 A305 完整包保留三段游戏资源。ARM32 使用 A321 WSA 测试包的引擎和应用代码。ARM64 同步引擎、好友数据逻辑和动态资源，保留 ARM64 专用宿主和资源入口。

```powershell
python scripts/build_aster_release_a321.py --test D:/Aster-builds/A321/PvZ2-Unline-Aster-A321-ARM32-WSA-existing-data.apk --base D:/Aster-builds/A305/release --output D:/Aster-builds/A321/release --sdk D:/Android/Sdk --signing D:/Signing/aster.json
```

构建脚本会核对 A305 完整底包和 A321 测试包的差异，并检查成品签名、ZIP 对齐与文件内容。完整包的全新安装尚未在设备上验收。
