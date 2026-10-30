# 自带转写工具的完整包

基础`media-editor.zip`只有Skill与配套脚本，不包含转写程序、Python或模型。只有视频/录音时，优先从同版Release下载对应的完整包，不把“Skill安装成功”报告成“转写已就绪”。

| 电脑 | 完整包 |
| --- | --- |
| Windows 64位Intel/AMD | `media-editor-windows-x64.zip` |
| Mac苹果芯片（M系列） | `media-editor-macos-arm64.zip` |
| Mac Intel芯片 | `media-editor-macos-x64.zip` |

每包只有一个`media-editor`Skill文件夹，包含便携Python、FFmpeg/ffprobe、Whisper本地程序、语音模型和链接获取模块。无需API Key，不依赖Workbuddy有没有AudioTranscribe。解压保留整个文件夹；不能混用不同系统的程序。构建时的FFmpeg仅启用常见本地媒体格式和必要的音频/画面处理，不包含网络协议或第三方编码库；PNG所需zlib同样从固定源码构建。

## 安装和执行

安装目录以当前Agent的实际技能目录为准，素材和输出放在安装目录之外。Windows示例：

```bat
"<解压目录>\media-editor\media-editor.cmd" install --target "<Agent技能目录>\media-editor"
"<安装目录>\media-editor.cmd" doctor --task local-asr
"<安装目录>\media-editor.cmd" transcribe "<本地音视频>" --language zh --output-dir "<新的转写目录>"
```

Mac示例（使用系统自带bash，不要求事先安装Python或Homebrew）：

```bash
bash "<解压目录>/media-editor/media-editor.command" install --target "<Agent技能目录>/media-editor"
bash "<安装目录>/media-editor.command" doctor --task local-asr
bash "<安装目录>/media-editor.command" transcribe "<本地音视频>" --language zh --output-dir "<新的转写目录>"
```

升级在安装命令最后加`--upgrade`，旧安装仍完整备份。完整包自动选用内置模型，不必填写`--model`；转写结束继续按统一标准编辑正文，不把ASR结果直接当成成稿。仅想执行配套脚本时，使用`runtime/runtime.json`中`python`字段指向的包内Python，例如`<包内Python> -B <脚本路径> ...`，不要另要求用户安装Python。

调用原有编辑工具时，在启动器后使用`core ...`、`multi ...`或`workspace ...`，分别转交内置单人／双人核心、多人工具及资料/计时工具；启动器只为该次进程提供包内FFmpeg与Python，不改电脑的全局PATH。

读取`doctor`的`ready`、`bundled_runtime`与`model`，不要只看退出码。它确认文件条件，不证明识别准确率；首次实际转写成功后再报告本机链路可用。包缺文件或系统不匹配时明确指出，不悄悄借用开发者预装工具或切到新的云服务。

## 能力范围

媒体转文字由包内程序在电脑上计算，不上传媒体。链接获取仍需联网并受原平台权限限制；Agent如何处理编辑阶段的文字取决于其自身服务，不能因此宣传整个Agent完全离线。此包不包含自动多人认人或真实原声听辨模型，不能因转写工具齐全就宣称署名已核实。

每个平台的安装、中文空格路径、真实转写和缓存续用检查以同版Release附带的`*.verify.json`为准；其他系统版本和Agent客户端不自动视为通过。Mac或Windows首次运行下载的程序可能显示系统安全提示，应按系统正常确认流程处理，不关闭安全机制。

## 维护者构建与验收

依赖来源与哈希固定在`assets/runtime-lock.json`。在目标系统运行`python scripts/build_offline_bundle.py --target <平台> --cache <独立缓存目录> --output <新的ZIP>`；本地已有相同模型可加`--model-dir`复用，经校验后才使用。Windows构建使用MSYS2/UCRT64编译FFmpeg，Whisper使用系统CMake/MSVC；使用仓库的多平台工作流可在对应原生系统构建。

用`python scripts/verify_offline_bundle.py <ZIP> --report <验收JSON>`验证。该检查在只保留系统PATH的环境中，调用包内Python完成安装，并用随Whisper源码提供的公开英文录音检验真实转写、中文文件路径、原件保护与续用；Mac额外限制该次转写的网络访问。它不上传私人素材，也不替代真实中文整场准确率、文字质量与人工终审。
