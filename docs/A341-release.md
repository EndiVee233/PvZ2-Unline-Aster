# PvZ2-Unline:Aster A341 正式版

**不推荐 ARM64，优先使用 ARM32。** ARM32 的 PVP 阳光预算与配置同步已在 WSA 验证。ARM64 使用相同的游戏引擎，尚未在设备上验收。

## PVP 与好友

- 预设阵容编辑和新匹配的默认阳光上限都是 **6500**。超额阵容可以打开修改，降到上限以内才能保存。开启「联网获取PVP关卡」后，游戏会同步线上设置，断网时沿用最近一次有效配置。 [阳光上限配置](https://github.com/EndiVee233/PvZ2-Unline-Aster/blob/main/pvp-presets/catalog.json)
- PVP 使用原生三倍速按钮，普通关卡继续使用二倍速。每位好友出借的每种植物每天可以借一次。
- 导出的玩家数据以「玩家名.json」命名。

## 关卡与界面

- 社交版星级挑战新增简单、普通和困难。简单可直接多选星，普通领取三星罐头后可多选，困难领取三星罐头后每局选一星。多选通关后，所获星级共享本局阵容记录。
- 坚不可摧在点击「开始战斗」后计时。战术黄瓜增加使用确认，开场会描边标出全部选中的星星。
- 签到恢复经典五列布局，整株植物奖励使用植物本体图。
- 修复埃及僵尸博士的召唤与眩晕特效、进阶预览切换时的音效叠加，以及爆炸震屏瞬间的画面偏移。移除幸运宝藏、金豆兑换页签和购买小推车弹窗。

## 构建

两份 APK 都内置 A325 的三卷完整资源。构建检查覆盖签名、ZIP 对齐和游戏引擎一致性。完整包的全新安装待设备验收。

```powershell
python scripts/build_aster_release_a341.py --test D:/Aster-builds/A341/PvZ2-Unline-Aster-A341-ARM32-WSA-existing-data.apk --base D:/Aster-builds/A325/release --output D:/Aster-builds/A341/release --sdk D:/Android/Sdk --signing D:/Signing/aster.json
```
