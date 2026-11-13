[中文](README.md) | [English](README.en.md)

# Qianyu (千鱼)

Qianyu is a Windows desktop application for running a customizable QQ chatbot. It brings together a local management interface, a modified [MaiBot](https://github.com/Mai-with-u/MaiBot) conversation engine, the [MaiBot QQ connector](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter), and a separately downloaded [NapCat](https://github.com/NapNeko/NapCatQQ) runtime. You provide your own QQ account and model API credentials.

This repository contains the **0.3.14 clean source snapshot**. The project is an early Windows development preview, not a turnkey hosted service. Its interface and bundled user documentation are currently in Chinese.

## What it does

- Runs a desktop management interface for configuring the model, QQ connection, chat scope, and bot instance.
- Supports group chat and optional private chat, with controls for calls, follow-up conversations, and the chance of starting a new topic. A 0% new-topic setting does not disable replies to calls or ongoing conversations.
- Lets users create their own persona, writing style, manual notes, and knowledge files. Optional long-term memory can connect relevant group and private conversations for the same user and bot account.
- Provides optional image understanding when the configured model supports it. A project-specific safeguard can limit repeated exchanges with accounts identified as the fish character; identity inference can be wrong and can be corrected manually.
- Keeps each user's configuration, QQ login data, chats, and memories in their own local instance. A clean new instance does not include the author's personal data, persona, writing style, or knowledge. Its default display name is `DeepSeek`, with a neutral assistant identity; automatic long-term memory and emoji collection are off by default.

Model calls, vision features, and memory retrieval depend on the selected provider and configuration and may incur charges. Local storage does **not** mean all processing is offline: relevant chat context and selected persona, memory, or knowledge content may be sent to the model service you configure.

## Status and limitations

- The supported target for this preview is **64-bit Windows**. Linux and cloud deployment have not been accepted as supported distributions.
- The connection and reply flows have been exercised with local simulated QQ and model services. The 0.3.14 acceptance did not include sending real QQ test messages or calling a paid model; real-world model behavior and QQ operation still need validation.
- The 0.3.14 installer is an **unsigned preview**. Windows may warn about or block it; the final installer has not been fully validated on a separate, clean computer. Do not disable Windows protections to run it.
- The installer can upgrade an existing installation after a manual download, with a backup and rollback mechanism. Automatic online update checks and downloads are not implemented.
- QQ account and third-party service requirements and risks are separate from this project. Review the applicable services' terms and use an account appropriate for testing.

## Getting started with a release

If a release package is available from the project maintainer, use the Windows installer or the **complete** clean ZIP, and keep all files together. The source-only repository does not include the prebuilt launcher or setup assistant, so the `.cmd` files in a fresh source checkout cannot run successfully by themselves.

1. Prepare a 64-bit Windows 10/11 computer, internet access, a QQ account for the bot, and a model API endpoint, model ID, and API key. Initial setup downloads dependencies and is not an offline installation.
2. For the clean ZIP, extract the whole archive and run `安装千鱼.cmd` from the extracted package root. Alternatively, follow the installer prompts if you have the matching installer.
3. Open Qianyu, enter your model settings, prepare the QQ connection, and scan the QR code with the intended QQ account.
4. Choose the chat scope before starting the conversation engine. **A new instance defaults to all groups joined by the bot account; private chat is off.** For an initial trial, select only a test group you control.
5. Confirm both that QQ is connected and that the conversation engine is ready. These are separate states. Add a persona or knowledge files if desired.

The packaged Chinese manual, `操作手册.md`, explains the full setup. Availability and paths can differ between a source checkout and a release package.

## Building from source

The source build targets Windows x64 with Python 3.12 and the .NET Framework C# compiler available. From the repository root, run:

```powershell
py -3.12 scripts/build_desktop.py
```

The build script compiles the launcher and setup assistant, creates a clean ZIP, and builds the installer and checksum files. It writes generated files into the working tree and an output directory; use a separate checkout and do not run it against a personal instance. A build without a valid code-signing certificate is unsigned. A checksum checks file integrity but does not establish publisher identity.

The release builder uses an explicit file list and requires its listed inputs, including the bundled distribution manual. If a repository layout differs from the release source layout, check the build script's paths before building. This command and the publicly hosted repository layout have not been independently validated on a clean machine for this README.

## Repository layout

| Path | Purpose |
| --- | --- |
| `fatfish/` | Desktop management application, instance management, and integration code |
| `engine/MaiBot/` | Modified MaiBot conversation engine |
| `components/` | QQ connector and project-specific extensions |
| `scripts/` | Build, setup, and maintenance tools |
| `templates/` | Clean-instance and distribution templates |
| `tests/` | Project tests |
| `upstream.lock.json` | Upstream sources, pinned revisions, and local modifications |
| `THIRD_PARTY.md` | Third-party sources, attribution, and license information |

Runtime instances, local environments, secrets, login sessions, chat histories, private knowledge, memories, and personal backups are not part of the clean source snapshot. Do not upload your own instance or backup to a public repository.

## Licenses and attribution

- Project-owned source and the modified MaiBot source are distributed under GPL-3.0; see [LICENSE](LICENSE), `engine/MaiBot/LICENSE`, and [THIRD_PARTY.md](THIRD_PARTY.md). The QQ connector and other dependencies retain their own license notices.
- The theme artwork and derived icons are **not relicensed under the GPL**. The project's attribution states that the selected artwork follows CC BY-NC-SA 4.0, with non-commercial and attribution requirements. See `fatfish/web/assets/ATTRIBUTION.md` and `fatfish/web/assets/sources.json` for creators, sources, and details.
- NapCat is downloaded separately at runtime; its binaries are not bundled in this source snapshot. Its license includes restrictions, including non-commercial terms; see `templates/NapCat-LICENSE.txt` and the relevant upstream terms. The QQ client is also not bundled and has its own terms.

The licenses of the code, artwork, and separately obtained components are different. Check all applicable terms before redistributing the complete application or using it commercially.
