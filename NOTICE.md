# 版权声明

Copyright (C) 2025–2026 千羽

本仓库发布的是「千鱼」0.3.14 中性纯净版的通用源码与模板。

## 1. 程序源码

本项目自有源码，以及对 [MaiBot](https://github.com/Mai-with-u/MaiBot) 所作的本地修改，按 **GNU General Public License v3.0**（GPL-3.0）许可。完整文本见根目录 [`LICENSE`](LICENSE)。上游 MaiBot 本身也是 GPL-3.0，其许可证保留在 `engine/MaiBot/LICENSE`。对本项目的修改边界见 `upstream.lock.json`。

按 GPL-3.0 分发、修改或再发布时，须保留版权与许可声明，并履行源码提供等法定义务。程序按“原样”提供，不附带适销性、特定用途适用性等担保。详细免责条款以 LICENSE 为准。

## 2. 不能按无限制 GPL 使用的部分

下面这些内容**不**因放在同一仓库里就改授为 GPL，再分发时必须遵守其原来的条款：

### 界面主题图片（CC BY-NC-SA 4.0）

目录：`fatfish/web/assets/`

- 角色原作：上善无形
- DeepSeek 鲸鱼娘二次设计：ZipZipPipe
- 公开同人档案：[EDMOK/blue-fish-archive](https://github.com/EDMOK/blue-fish-archive)，展示站 https://fisharchive.cc/

按来源声明，这些图片及由它们生成的图标遵循 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)：

- 仅限非商业使用
- 必须保留署名与本说明
- 改编或再分发须以相同方式共享
- **权利不改授为程序的 GPL 许可**

本项目只对公开原图做了等比缩小和 WebP / PNG / ICO 格式转换，没有改画面内容。详细哈希与来源见该目录下的 `ATTRIBUTION.md` 与 `sources.json`。个人图库和私人图像不在本仓库中。

### NapCat

[NapCat](https://github.com/NapNeko/NapCatQQ) 使用有限分发许可，不能把它当成无限制开源软件。完整条款见 `templates/NapCat-LICENSE.txt`。本仓库不内嵌 NapCat 二进制；程序只在运行时按官方来源获取，使用仍须遵守其许可。

### QQ 客户端

QQ 是腾讯的官方客户端，由使用者自行安装并遵守其许可。本仓库和纯净发行包都不分发 QQ 客户端。

### 其他第三方依赖

Python 包、pywebview、uv、MaiBot 官方 QQ 连接器等，各从其发行包内的许可证。清单和说明见 [`THIRD_PARTY.md`](THIRD_PARTY.md)。不得把第三方组件的许可改写成 GPL。

## 3. 隐私与密钥

仓库中不应包含：

- 个人实例（`instances`）
- QQ 登录态
- API 密钥或 `.env`
- 个人知识、记忆、聊天数据库
- 本机运行时目录或备份

API 由使用者自己配置。一旦启用，相关聊天、人格和所选资料会发送给其配置的模型服务商。

## 4. 署名与联系

维护者：千羽（GitHub：[qy70](https://github.com/qy70)）

如需引用本项目，请同时保留第 1 节的 GPL 声明，以及第 2 节对主题图、NapCat 和其他第三方组件的原许可说明。
