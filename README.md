# 捞鱼同步小助手 Laoyu Sync

给 [Syncthing](https://syncthing.net) 做的中文友好套壳：本地核心服务 + 网页管理界面，
让“添加设备、共享文件夹”不再折磨人。桌面小精灵（../syncthing-pet）是它的第一个插件。

## 快速开始

双击 `启动捞鱼同步小助手.bat`（需要已安装 Syncthing 和 Python 3.12+）。

- 首次运行会自动拉起 Syncthing 引擎（没有就提示安装）
- 管理界面：`http://127.0.0.1:8384` 是原生高级设置，`http://127.0.0.1:8390` 是捞鱼同步小助手

## 添加一台设备，只要三步

1. 「设备与配对」页复制本机设备 ID（或让对方扫二维码）
2. 把对方 ID 粘进“添加设备”，勾选要共享的文件夹
3. 对方点一下接受，开始同步

## 目录与开发

接手开发先读 [SKILL.md](SKILL.md) 和 [docs/agent.md](docs/agent.md)。
调试：`python core/app.py --console`。

## License

MIT（本壳）。Syncthing 为 MPL-2.0，归其作者所有。
