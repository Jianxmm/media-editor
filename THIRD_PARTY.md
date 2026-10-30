# 外部工具与许可

基础Skill包通过命令行调用已有工具；转写完整包额外分发便携Python、FFmpeg/ffprobe、whisper.cpp、Whisper模型和yt-dlp源码模块。具体版本、来源与哈希保存在`runtime/runtime.json`与`assets/runtime-lock.json`，第三方许可随`runtime/licenses/`及Python运行目录保留。第三方组件不因本项目MIT许可而改变许可。

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：按需获取用户有权限访问的音视频或字幕。
- [FFmpeg](https://ffmpeg.org/legal.html)：探测和处理音视频；不同构建的许可可能不同。
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)：本地转写工具（MIT）；基础包需另备模型，完整包包含固定版本的ggml语音模型。
- [python-build-standalone](https://github.com/astral-sh/python-build-standalone)：完整包使用的便携CPython，保留运行目录内的许可与说明。

完整包中的FFmpeg由本项目从所列源码构建，未启用GPL、nonfree或外部编码库；PNG所需zlib同样从固定源码构建，保留其许可。源码原包与构建参数随`runtime/sources/`和构建脚本提供。Whisper与yt-dlp原始源码同样随包保留。FFmpeg部分代码基于Independent JPEG Group的工作，相关源文件未经本项目修改。

完整包的`runtime/samples/jfk.wav`随whisper.cpp上游源码提供，仅用于验证安装和识别链路，不作为中文或长场内容质量标杆。不包含用户真实录音。

模型许可也随包保留：Whisper权重的OpenAI MIT声明来自`openai/whisper@86098128c0b4f24f0e2aa2994de830614b474227`，Silero VAD的MIT声明来自`snakers4/silero-vad@066409f3d9db45a30d21dfcbf9147826ffdd7052`，存于`assets/runtime-licenses/`并复制到完整包的许可目录。

内置直播核心的依赖、模型来源与许可另见 [.livestream-core/THIRD_PARTY.md](.livestream-core/THIRD_PARTY.md)。

设计方法参考[音视频转录与长文整理](https://scys.com/skillhub/skills/skl_media-transcriber?from=copy_link&v=1.1.0)；本包不包含该 Skill 的源码或正文。外部作品的权利归其权利人，不能因本包提供 MIT 许可而推断外部模型、素材或其他 Skill 的许可。
