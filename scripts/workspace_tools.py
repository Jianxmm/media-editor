#!/usr/bin/env python3
"""Consistent optional profile access and presentation of supplied review issues."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit
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
    pending={'待确认','待核'}
    methods={'已回听':{'真人回听','音频理解'},
             '已资料核对':{'资料核对','回放画面'},
             '已保守表达':{'保守改写'},'已删除':{'删除'}}
    rows=[];seen_ids=set();locations=set();states={};records=[]

    def cell(value):
        return str(value).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('|','\\|').replace('\r\n','\n').replace('\r','\n').replace('\n','<br>')

    def reference(value, label, check_anchor=False):
        if not isinstance(value,str) or not value.strip():raise ValueError(label+'需要有效位置')
        parts=urlsplit(value)
        if parts.scheme in {'http','https'} and parts.netloc:return value, None
        if parts.scheme or parts.netloc:raise ValueError(label+'仅支持本机文件或http/https资料')
        target=(source.parent/unquote(parts.path)).resolve()
        if not target.is_file():raise ValueError(label+'文件不存在：'+value)
        if check_anchor and parts.fragment:
            fragment=unquote(parts.fragment)
            content=target.read_text(encoding='utf-8-sig')
            explicit=re.search(r"id=[\"']"+re.escape(fragment)+r"[\"']",content)
            headings=re.findall(r'^#{1,6}\s+(.+?)\s*#*$',content,re.M)
            heading_match=any(re.sub(r'[^\w\s-]','',h).strip().lower().replace(' ','-')==fragment for h in headings)
            if not explicit and not heading_match:raise ValueError(label+'锚点不存在：'+value)
        local=quote(Path(os.path.relpath(target,output.parent.resolve())).as_posix(),safe='/')
        return urlunsplit(('', '', local, parts.query, parts.fragment)),target

    for index,item in enumerate(issues):
        if not isinstance(item,dict) or item.get('priority') not in ('P0','P1','P2'):
            raise ValueError('每条问题需要保留原有 P0/P1/P2 级别')
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ('location','original','question')):
            raise ValueError('每条问题都需要原文位置、原句和具体疑点')
        ident=item.get('id')
        if ident is not None:
            if not isinstance(ident,str) or not ident.strip() or ident in seen_ids:
                raise ValueError('问题编号必须非空且不重复')
            seen_ids.add(ident)
        scope=item.get('scope','local')
        if scope not in {'local','global'}:raise ValueError('scope仅支持local或global')
        state=item.get('status','待确认')
        if state not in pending and state not in methods:raise ValueError('不支持的核对状态：'+str(state))
        source_link=None;clip_link=None
        if item.get('source_link'):source_link,_=reference(item['source_link'],'原文索引',True)
        if item.get('clip'):
            if urlsplit(item['clip']).scheme or urlsplit(item['clip']).netloc:
                raise ValueError('回听clip必须指向已存在的本机片段')
            clip_link,_=reference(item['clip'],'回听',False)
        if state not in pending:
            review=item.get('review')
            if not isinstance(item.get('finding'),str) or not item['finding'].strip():
                raise ValueError('已处理项必须保留具体结论finding')
            if not isinstance(review,dict) or not all(isinstance(review.get(k),str) and review[k].strip() for k in ('method','reviewer','checked_at')):
                raise ValueError('已处理项需要方法、核对人和核对日期记录')
            if review['method'] not in methods[state]:raise ValueError('状态与核对方法不符；辅助ASR不等于回听')
            evidence=review.get('evidence')
            if not isinstance(evidence,list) or not evidence:raise ValueError('已处理项需要对应证据入口')
            evidence_links=[];evidence_paths=[]
            for number,value in enumerate(evidence,1):
                link,path=reference(value,'核对证据',True)
                evidence_links.append('[证据'+str(number)+']('+link+')')
                if path:evidence_paths.append(path)
            if state=='已保守表达':
                if not isinstance(item.get('draft'),str) or not item['draft'].strip():raise ValueError('已保守表达必须引用正文实际写法')
                candidates=[p for p in evidence_paths if p.suffix.lower() in {'.md','.txt'}]
                if not any(item['draft'] in p.read_text(encoding='utf-8-sig') for p in candidates):
                    raise ValueError('保守写法未在提供的正文证据中找到')
            records.append((ident or str(index+1),review,evidence_links,item['finding']))
        origin=item.get('source','本场原稿')
        locations.add((origin,item['location']))
        states[state]=states.get(state,0)+1
        rows.append((item,scope,state,source_link,clip_link,index))

    # 不按同一时间位置合并结论；不同优先级在整张表中排序。
    rows.sort(key=lambda row:(row[0]['priority'],row[0].get('source','本场原稿'),row[0]['location'],row[5]))
    global_rows=[row for row in rows if row[1]=='global']
    local_rows=[row for row in rows if row[1]=='local']
    summary='、'.join(state+str(count)+'项' for state,count in states.items()) or '无待列问题'
    text=['# 待核对清单\n\n',f'共 {len(issues)} 项，涉及 {len(locations)} 个原文位置；{summary}。\n\n',
          '状态依据已提供的记录呈现；资料核对、保守表达和删除不等于听清原声。本清单不代表发布终审。\n\n']
    if global_rows:
        text.append('## 整场核验条件\n\n')
        for item,_,state,source_link,clip_link,_ in global_rows:
            label=item.get('title') or item.get('type') or '整场条件'
            ident='（'+cell(item['id'])+'）' if item.get('id') else ''
            text.append('- **'+item['priority']+' · '+cell(label)+ident+'**：'+cell(item['original'])+'<br>需核对：'+cell(item['question'])+'<br>状态：'+state+'。')
            if source_link:text.append(' [来源]('+source_link+')')
            if clip_link:text.append(' [原声]('+clip_link+')')
            if item.get('finding'):text.append(' 记录结论：'+cell(item['finding']))
            text.append('\n')
        text.append('\n')
    if local_rows:
        text.append('## 逐项问题\n\n| 级别 | 时间码 | 问题类型 | 原文/成稿 | 处理建议 | 状态 |\n| --- | --- | --- | --- | --- | --- |\n')
        for item,_,state,source_link,clip_link,_ in local_rows:
            position=cell(item['location'])
            if source_link:position='['+position+']('+source_link+')'
            if item.get('source','本场原稿')!='本场原稿':position=cell(item['source'])+'<br>'+position
            if clip_link:position+='<br>[原声]('+clip_link+')'
            original='原文：'+cell(item['original'])
            if item.get('draft'):original+='<br>成稿：'+cell(item['draft'])
            action=cell(item['question'])
            if item.get('action'):action+='<br>'+cell(item['action'])
            if item.get('finding'):action+='<br>记录结论：'+cell(item['finding'])
            label=cell(item.get('type') or item.get('title') or '内容核对')
            if item.get('id'):label+='（'+cell(item['id'])+'）'
            text.append('| '+item['priority']+' | '+position+' | '+label+' | '+original+' | '+action+' | '+state+' |\n')
    if not issues:text.append('本轮没有列出的待核问题；不代表所有事实已核实。\n')
    if records:
        text.append('\n<details>\n<summary>核对记录与证据</summary>\n\n')
        for ident,review,evidence,finding in records:
            text.append('- **'+cell(ident)+'**：'+cell(review['method'])+'；'+cell(review['reviewer'])+'；'+cell(review['checked_at'])+'。'+cell(finding)+' '+ ' · '.join(evidence)+'\n')
        text.append('\n</details>\n')
    result=''.join(text);output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_symlink():raise ValueError('不能覆盖链接')
    if output.exists() and output.read_text()!=result:raise FileExistsError('已有不同清单，保留人工版本；请另存新文件。')
    if not output.exists():
        with output.open('x',encoding='utf-8') as f:f.write(result)
    return {'path':str(output),'issues':len(issues),'locations':len(locations),
            'global_issues':len(global_rows),'states':states,
            'status':'待核' if any(state in pending for state in states) else '记录已呈现'}


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
