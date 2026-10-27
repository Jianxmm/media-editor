#!/usr/bin/env python3
"""Consistent optional profile access and presentation of supplied review issues."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parent))
from local_support import profile_core, profile_terms


def stage_time(workspace: Path, action: str, stage: str):
    if not stage.strip():raise ValueError('请给出阶段名称')
    folder=workspace/'_work/耗时';folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(stage.encode()).hexdigest()[:20];path=folder/(key+'.json')
    if path.is_symlink():raise ValueError('耗时记录不能为链接')
    if action=='start':
        if path.exists():raise FileExistsError('该阶段已有记录，使用新的具体阶段名以保留历史。')
        result={'stage':stage,'started':time.time(),'status':'running'}
        with path.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False)
    else:
        result=json.loads(path.read_text())
        if result.get('stage')!=stage or result.get('status')!='running':raise ValueError('没有对应的未结束阶段')
        ended=time.time();elapsed=ended-result['started']
        if elapsed<0:raise ValueError('系统时间发生变化，不能计算耗时')
        result.update(ended=ended,elapsed_seconds=round(elapsed,3),status='finished')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def time_report(workspace: Path):
    entries=[]
    for path in workspace.rglob('.run-times.jsonl'):
        if path.is_symlink():continue
        for line in path.read_text().splitlines():
            row=json.loads(line);entries.append((path.relative_to(workspace).as_posix(),row))
    folder=workspace/'_work/耗时'
    if folder.is_dir():
        for path in sorted(folder.glob('*.json')):
            if not path.is_symlink():entries.append((path.relative_to(workspace).as_posix(),json.loads(path.read_text())))
    lines=['# 本次任务耗时\n\n','以下只记录实际测量；工具和编辑阶段分别列出，不直接相加为总耗时。人工核对用时未记录时保持未知。\n\n',
           '| 阶段 | 实际秒数 | 来源 |\n| --- | ---: | --- |\n']
    for source,row in entries:
        seconds=row.get('elapsed_seconds','进行中/未结束')
        stage=str(row.get('stage','未知阶段')).replace('|','／').replace('\n',' ')
        lines.append(f'| {stage} | {seconds} | {source} |\n')
    if not entries:lines.append('| 尚无记录 | 未测量 | — |\n')
    report=workspace/'运行耗时.md'
    if report.is_symlink():raise ValueError('耗时摘要不能为链接')
    # This generated summary contains no review decisions; source records remain.
    if report.exists() and not report.read_text().startswith('# 本次任务耗时\n'):
        raise FileExistsError('已有人工文件，不覆盖')
    report.write_text(''.join(lines),encoding='utf-8')
    return {'path':str(report),'measured_records':len(entries),'human_review':'未自动计时'}


def render_review(source: Path, output: Path):
    data=json.loads(source.read_text(encoding='utf-8-sig'))
    issues=data.get('issues')
    if not isinstance(issues,list):raise ValueError('缺少 issues 问题列表')
    groups={}
    for item in issues:
        if not isinstance(item,dict) or item.get('priority') not in ('P0','P1','P2'):
            raise ValueError('每条问题需要保留原有 P0/P1/P2 级别')
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ('location','original','question')):
            raise ValueError('每条问题都需要原文位置、原句和具体疑点')
        link=None
        if item.get('clip'):
            clip=(source.parent/item['clip']).resolve()
            if not clip.is_file():raise ValueError('回听文件不存在，请修正链接或明确只保留原文时间：'+str(item['clip']))
            link=quote(Path(os.path.relpath(clip,output.parent.resolve())).as_posix(),safe='/')
        groups.setdefault((item.get('source','本场原稿'),item['location']),[]).append((item,link))
    ordered=sorted(groups.items(),key=lambda x:(min(int(row[0]['priority'][1:]) for row in x[1]),x[0]))
    text=['# 待核对清单\n\n',f'共 {len(issues)} 个问题，按 {len(groups)} 个原文位置归组。先处理 P0/P1，再看一般检查；同处的独立疑点全部保留。\n\n',
          '本页只整理已提供的问题，不代表已经听清、事实核实或人工终审。核实后的结论仍须回填原任务记录。\n\n']
    if not issues:text.append('本轮没有列出的待核问题；不代表所有事实已核实。\n')
    for number,((origin,location),rows) in enumerate(ordered,1):
        level=min(int(row[0]['priority'][1:]) for row in rows)
        text.append(f'## {number}. {location} · P{level}\n\n来源：{origin}\n\n')
        originals=list(dict.fromkeys(row[0]['original'] for row in rows))
        for value in originals:text.append('原文：\n\n> '+value.replace('\n','\n> ')+'\n\n')
        for item,link in rows:
            text.append('- **'+item['priority']+' · 核对什么**：'+item['question']+'\n')
            if item.get('draft'):text.append('  - 当前稿采用：'+item['draft']+'\n')
            text.append('  - 怎样核对：'+item.get('action','对照原文及可用原声确认；无法确认时保留待核或按原有规则保守处理。')+'\n')
            if link:text.append('  - [打开回听片段]('+link+')\n')
        text.append('\n状态：待核；未由本工具自动关闭问题。\n\n')
    result=''.join(text);output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_symlink():raise ValueError('不能覆盖链接')
    if output.exists() and output.read_text()!=result:raise FileExistsError('已有不同清单，保留人工版本；请另存新文件。')
    if not output.exists():
        with output.open('x',encoding='utf-8') as f:f.write(result)
    return {'path':str(output),'issues':len(issues),'locations':len(groups),'status':'待核'}


def main():
    parser=argparse.ArgumentParser(description='个人词库及待核清单助手')
    commands=parser.add_subparsers(dest='command',required=True)
    profile=commands.add_parser('profile');profile.add_argument('action',choices=['init','check','snapshot'])
    profile.add_argument('directory',type=Path);profile.add_argument('--workspace',type=Path)
    review=commands.add_parser('review');review.add_argument('source',type=Path);review.add_argument('--output',type=Path,required=True)
    clock=commands.add_parser('time');clock.add_argument('action',choices=['start','end','report']);clock.add_argument('--workspace',type=Path,required=True);clock.add_argument('--stage')
    args=parser.parse_args()
    try:
        if args.command=='review':result=render_review(args.source,args.output)
        elif args.command=='time':
            result=time_report(args.workspace) if args.action=='report' else stage_time(args.workspace,args.action,args.stage or '')
        else:
            core=profile_core()
            if args.action=='init':
                skill=Path(__file__).resolve().parents[1];dest=args.directory.expanduser().resolve()
                if dest.is_relative_to(skill) or skill.is_relative_to(dest):raise ValueError('词库应保存在技能安装目录之外')
                result=core.init_profile(args.directory)
            else:
                terms=profile_terms(args.directory)
                if args.action=='snapshot':
                    if not args.workspace:raise ValueError('请给出本次任务目录 --workspace')
                    if args.workspace.resolve().is_relative_to(Path(__file__).resolve().parents[1]):raise ValueError('任务目录应在技能安装目录之外')
                    result=core.snapshot_profile(args.workspace,args.directory)
                else:result=core.inspect_profile(args.directory)
                result['confirmed_terms']=terms
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'blocked','reason':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
