# 来源与分发说明

本项目基于 MaiBot 进行应用集成，保留上游来源与许可。大肥鱼新增源码随本项目按 GPL-3.0 分发，根目录 LICENSE 提供许可证文本。

| 组件 | 来源 | 许可信息 |
| --- | --- | --- |
| MaiBot | https://github.com/Mai-with-u/MaiBot | GPL-3.0，完整许可证保留在 engine/MaiBot/LICENSE |
| MaiBot 官方统一 QQ 连接器 | https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter | 上游 manifest 声明 GPL-v3.0-or-later，来源与声明保留 |
| MaiBot Plugin SDK | Python 依赖 maibot-plugin-sdk | 使用对应固定版本包内声明 |
| MaiBot Dashboard | Python 依赖 maibot-dashboard | 使用对应固定版本包内声明与源码来源 |
| 其他 Python 依赖 | requirements-windows.lock | 分别遵循其发行包内许可证；本版通过安装入口获取，不重写其许可 |
| uv | https://github.com/astral-sh/uv | 仅作为依赖安装工具下载使用，保留官方来源 |
| NapCat | https://github.com/NapNeko/NapCatQQ | 有限分发许可，不能等同于无限制开源；不捆绑其二进制或 QQ 客户端 |
| QQ | 腾讯官方客户端 | 用户自行准备并按客户端许可使用，不随本包分发 |

保留上游版权、许可证和来源，不把上游功能宣称为本项目独立研发。分发修改版时履行适用的源码提供义务。NapCat、QQ 的账号风险与运行要求独立于模型 API。

2026-11-04，千羽 0.3.7 将本机已验证的话题接话扩展纳入纯净发行包：新实例使用通用话题设置，模型判断相关话题和呼叫，略过的闲聊只作历史，不按积压条数集中补答。MaiBot 修改边界记录在 upstream.lock.json，修改后的完整源码随包分发。操作手册和配图由本项目制作，截图来自空白隔离实例，不包含私人账号或资料。

2026-11-04，千鱼 0.3.4 在锁定的 MaiBot 源码上增加本地逐条回复模式：配置字段、调度与消费队列、原生回复执行分支；配置版本升为 8.15.69。上游来源和提交保持不变，修改文件及用途列在 upstream.lock.json 的 local_modifications 中，修改后的完整源码随纯净包分发。

2026-11-04，DFake 0.3.5 为用户要求的大肥鱼主题选取公开插画用于界面背景、形象与程序图标。素材目录 `fatfish/web/assets` 的 `ATTRIBUTION.md` 与 `sources.json` 保留角色原作上善无形、二次设计 ZipZipPipe、公开档案 EDMOK/blue-fish-archive、固定来源与哈希，遵循来源的 CC BY-NC-SA 4.0 声明；仅非商业，图片权利不改授程序 GPL。只缩小及转换格式，未改画面内容。这些单独选取的通用主题素材与不分发的个人实例图库分别处理。

## 0.2.0 桌面版补充

QQ 接入改为应用启动时从 NapCat 官方固定版本获取原始 Windows Node 组件，安装包本身不嵌入 NapCat/QQ 二进制。组件位置、来源与 SHA256 见 fatfish/qqtool.py；完整 NapCat 许可见 templates/NapCat-LICENSE.txt，下载使用仍须遵守其许可及腾讯相关条款。QQ 登录资料只写入个人实例，不随纯净包分发。

桌面窗口使用 pywebview（BSD-3-Clause）与系统 Edge WebView2；二维码使用 qrcode（BSD）。依赖保留各自发行包的许可，不将第三方组件的许可改为本项目 GPL。

千鱼自然对话包参考 op7418/Humanizer-zh 的中文编辑方法，做成适用于 QQ 对话的规则；对应 MIT 版权与许可保留在 templates/style-packs/qianyu-tieba/Humanizer-zh-LICENSE.txt。游戏对白部分只转用用户既有研究中的机制，不分发原游戏对白或资源；所有示范回复为本项目原创。其他公开参考见该风格模板的 sources.md。


0.3.1 提供独立的表情导入工具，来源 https://github.com/Loping151/dsh-nekowhale-stickers ，媒体 https://kiriyuki.com ，作者可以叫我云大人/雾雪（https://space.bilibili.com/103739）。按该项目 LICENSE-ASSETS 的署名、非商业使用约定获取到个人实例，不内嵌图库或其 CC BY-NC 标注于 GPL 程序发行包，也不安装或分发 DSH 插件源码。
