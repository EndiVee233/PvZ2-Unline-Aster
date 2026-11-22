# Aster 外置存档

在标题画面打开扳手「设置」，点「外置存档」。选择「导出存档备份」，在系统文件选择器里保存到 Download、文档目录或自己的备份位置。备份文件名为 `Aster-save-日期-时间.zip`，可整份复制到另一台设备。

恢复时选择「从备份恢复」，打开 Aster 导出的 ZIP，再点「恢复并退出」。下次从应用入口打开游戏时会载入备份。恢复前的游戏存档保留在应用私有的 `files/.aster-before-restore-*/previous`。如需日后自行还原当前进度，先把当前进度另存一份 ZIP。

备份包括全体玩家、原生主档及其备份、关卡续打状态、Aster 的 PVP 存档、冒险成绩和阵型、头像与出借配置，以及已生成的社区公开编号。设备识别文件、日志、下载缓存、广告及支付数据库继续保存在本机。自制 PVP 关卡文件可从原有预设编辑器单独导出。

提供的中文版 1.7.5 APK 中，`AndroidGameApp.Resources_GetUserDataFolder()` 拼出 `/sdcard/Android/data/com.popcap.pvz2cthd/com.popcap.pvz2cthd` 后把目录交给原生引擎。Aster 目前同时使用私有的 `files/userdata` 和 `files/userdataNo_Backup` 保存不同数据。Aster 的外置 ZIP 将这两处游戏进度一起打包，可以保存到 Android 共享存储并独立于应用保留。游戏运行期间继续读写私有主档。
