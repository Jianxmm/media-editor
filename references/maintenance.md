# 由助手执行的词库、恢复与升级

普通使用者直接按首页的自然语言提需求。下面是助手需要的实际命令，`SKILL_ROOT` 必须替换为当前安装目录，任务和词库放在安装目录之外。

## 安装与升级

唯一推荐来源是 `https://github.com/Jianxmm/media-editor`，下载按钮指向当前最新版。源码仓库根目录就是统一 Skill；不需要另外安装直播核心。

```text
python <下载包>/install.py --target <实际技能目录>/media-editor
python <下载包>/install.py --target <实际技能目录>/media-editor --upgrade
python <下载包>/install.py --target <实际技能目录>/media-editor --restore <先前返回的备份目录>
```

普通用户从Release发行资产安装，Windows不把可能经Git改过换行的源码克隆当成发行包。完整包或已准备共用环境时使用`media-editor.command`／`media-editor.cmd`的`install`命令，避免另找Python。

新下载包先校验再操作；相同版本和内容重复安装返回 unchanged。不同版本或人工修改默认不覆盖；明确升级时旧安装完整移到技能扫描目录外的备份位置。复制新包失败会恢复旧安装。回退会保留原备份，并另备份回退前的安装。不要把用户资料迁入安装目录，不因升级重写历史稿。

## 一份词库用于各种素材

按 [共用词库](personalization.md) 处理，使用原有直播个人资料格式。

```text
python <SKILL_ROOT>/scripts/workspace_tools.py profile init <资料目录>
python <SKILL_ROOT>/scripts/workspace_tools.py profile check <资料目录>
python <SKILL_ROOT>/scripts/workspace_tools.py profile snapshot <资料目录> --workspace <普通任务目录>
```

直播初始化仍使用核心 `init --profile`；已有场次不偷偷补快照。可选本地转写参数 `--profile` 只提示已确认专名，不自动改事实或判断说话人。

## 下载与转写中断

下载使用相同链接、选项、输出目录再次执行 `media_intake.py fetch`，已绑定下载可继续；完成的素材指纹校验后复用，不重新访问网站。变更来源、人工修改成品或没有任务绑定时停止并保留现场。

转写同一媒体、模型和参数再次执行 `transcribe`。已经验证的分段和回听片段可复用，内容变化或缓存损坏仍拒绝。新版系统锁在进程退出/崩溃后自动释放，不要删除仍在运行的锁。旧版锁无法安全识别时先说明，不强行接管。

## 待核清单与耗时

清单使用[呈现规则](review-list.md)，按独立问题生成表格，保留原句、正文实际写法及已提供的核对记录；整场能力缺口集中说明。程序不执行听音、事实查证或发布终审，不降低P0/P1，也不把记录存在当作结论真实；用户不用维护中间JSON。

```text
python <SKILL_ROOT>/scripts/workspace_tools.py time start --workspace <任务目录> --stage 文字整理
python <SKILL_ROOT>/scripts/workspace_tools.py time end --workspace <任务目录> --stage 文字整理
python <SKILL_ROOT>/scripts/workspace_tools.py time report --workspace <任务目录>
```

工具耗时从任务下 `.run-times.jsonl` 汇总，编辑阶段需要实际开始/结束记录。报告分别列出，不将重叠阶段相加；人工核对没计时就写未知，不代填。相同阶段的后续迭代用新的具体名称，保留历史记录。
