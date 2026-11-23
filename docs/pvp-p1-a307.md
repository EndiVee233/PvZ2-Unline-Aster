# A307 花园战争 P1

- 邪恶戴夫仍在本地周二、周四、周六刷新。以刷新日的本地午夜为本次造访起点，一次造访有效 24 小时。街区显示与出击校验读取同一截止时间，已开始的战斗能继续结算。原资料未给离线时区下的具体起点，本次沿用现有的本地日历。[反馈视频 03:25](https://www.bilibili.com/video/BV1LjyWzREHo/?t=205)
- 第六胜先保存结算和待确认对话。退出重进或跨过刷新点时仍保留待确认对话，确认后才把原地块换回一个普通邻居。对话提交失败可重试。若邻居档先写成功而钱包档写失败，重试复用同一个替换结果。
- 实验室卡片的僵尸进阶、技能倒计时，以及 PVP 主界面的实验室倒计时使用现有截止时间和原生绘制。主界面在多项同时进行时显示最先完成的一项，结算或使用钻石完成后会移除相应倒计时。[反馈视频 06:06](https://www.bilibili.com/video/BV1LjyWzREHo/?t=366)
- A306 的 WSA 截图确认第三区两个模型依次是 HOT DOG 和 STORE，A307 据此显示「热狗店」和「商店」，并保留原地块 ID、存档和临时防守配置。每店保留离线空仓、每种货币容量 2,000、持有后每小时 40 紫星币及 20 勋章。侦察显示对战奖励，地图显示库存与产速。出击费、容量、产速、战斗地图别名及临时防守配置集中在商铺配置中。三星才转移归属。[商铺录像 04:31、05:34](https://www.bilibili.com/video/BV1GkyezmECn/?t=271)
- 原生戴夫头像保留。已从 A305 原生图集确认蓝色圆底与红胡子头像使用独立贴图。地图布局、队列、商铺空店阵容及音乐沿用现有内容。3 倍速、曲目细分和药剂禁用样式仍待同版证据。老视频中的有主商铺库存和阵容不能作为空店配置。

## 构建与检查

```powershell
python scripts/build_aster_p1.py --base D:/Aster-builds/A305/PvZ2-Unline-Aster-A305-ARM32-WSA-existing-data.apk --sdk Y:/Android/Sdk --headers work/feedback/A194/patched/generated --prior work/feedback/A194/patched/offline.elf --p0 D:/Aster-builds/A303/offline.elf --output D:/Aster-builds/A307
python scripts/check_aster_p1.py D:/Aster-builds/A307
python scripts/check_aster_pickup_access.py D:/Aster-builds/A307/libSrc.so
```

构建保留 A305 的资源、应用入口和已安装的 PvP 运行时存储布局。WSA 测试用 ARM32 签名包。验收需要在实际实验室卡片和 PVP 主界面观察计时，确认两间商铺的模型和标签，并在戴夫出现时复查头像、24 小时显示和退场顺序。
