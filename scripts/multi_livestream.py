#!/usr/bin/env python3
"""Source-bound, transcript-first multi-person editing. No diarization or AI calls.

Checks validate recorded evidence and provenance, not the truth of a listening claim.
Solo/dual implementations remain in the bundled, unchanged livestream core.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import functools
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'.livestream-core'
sys.path.insert(0,str(CORE/'scripts'))
from workspace import init_case, input_manifest_errors, subtitle_timing_errors, export_outputs
from source_turns import blocks_from_text
from route_livestream import SPEAKER_HEADER_RE, find_replay
from media_tools import duration, audio_clip
from personal_profile import validate_snapshot
from local_support import LocalLock

SOURCE=Path('inputs/02_带时间码原稿.md')
META=Path('_work/多人任务.json')
RECORD=Path('_work/多人编辑记录.json')
CLIPS=Path('_work/review_clips/manifest.json')
GENERATED=Path('_work/多人生成记录.json')
HUMAN=Path('_work/多人终审.json')
MAIN=Path('outputs/01_公众号可发布稿.md')
ISSUES=Path('outputs/02_待核问题清单.md')
REPORT=Path('outputs/03_编辑质检报告.md')
EDITOR_CHECKS=('facts','attribution','coverage','examples','limits','questions','ending')
POSITIONS={'opening':0,'quarter':.25,'middle':.5,'three-quarter':.75,'ending':1}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('记录不能为符号链接')
    body=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
        f.write(body);temp=Path(f.name)
    try:temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def local(case,rel):
    case=Path(case).resolve();rel=Path(rel)
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('任务内文件路径越界')
    path=case/rel
    if any((case/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):
        raise ValueError('任务材料不能经过符号链接')
    return path


def locked(func):
    @functools.wraps(func)
    def run(case,*args,**kwargs):
        case=Path(case).resolve()
        if case.is_relative_to(ROOT.resolve()) or ROOT.resolve().is_relative_to(case):raise ValueError('场次须在技能安装目录之外')
        with LocalLock(local(case,Path('_work/.multi.lock'))):return func(case,*args,**kwargs)
    return run


def source_blocks(case):
    text=local(case,SOURCE).read_text(encoding='utf-8-sig')
    rows=blocks_from_text(text);matches=list(SPEAKER_HEADER_RE.finditer(text))
    for i,(row,m) in enumerate(zip(rows,matches)):
        end=matches[i+1].start() if i+1<len(matches) else len(text)
        row['text']=text[m.end():end].strip()
        if not row['text']:raise ValueError('原稿包含空发言块')
    return rows


def bind(case):
    replay=find_replay(case)
    local(case,replay.relative_to(case))
    return {'replay':replay.relative_to(case).as_posix(),'replay_sha256':sha(replay),'source_sha256':sha(local(case,SOURCE))}


def nonblank(value):
    return isinstance(value,str) and bool(value.strip()) and not re.fullmatch(r'待填(?:写)?|待确认|未知|不确定|TODO',value.strip(),re.I)


def initialize(case,replay,transcript,*,layout='discussion',profile=None,participant_count=None):
    case=Path(case).expanduser().absolute()
    if case.is_symlink() or case.exists():raise FileExistsError('场次已存在，保留原稿；使用prepare继续')
    case=case.resolve()
    if case.is_relative_to(ROOT.resolve()) or ROOT.resolve().is_relative_to(case):raise ValueError('场次须在技能安装目录之外')
    if layout not in ('discussion','sequential'):raise ValueError('未知多人版式')
    # Shared parser/provenance/profile contracts; original source bytes stay intact.
    kind='strict' if Path(transcript).suffix.lower() in ('.srt','.vtt') else 'ordered-turns'
    case.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.multi-init-',dir=case.parent) as tmp:
        stage=Path(tmp)/'case'
        init_case(stage,Path(replay),Path(transcript),profile=profile,transcript_contract=kind)
        prepare(stage,layout=layout,participant_count=participant_count)
        stage.rename(case)
    return {'case':str(case),'status':'NEEDS_REVIEW','note':'已准备多人核对材料，尚未确认说话人或完成原声核对。'}


@locked
def prepare(case,*,layout=None,participant_count=None):
    case=Path(case).resolve()
    if case.is_relative_to(ROOT.resolve()) or ROOT.resolve().is_relative_to(case):raise ValueError('场次须在技能安装目录之外')
    rows=source_blocks(case);binding=bind(case)
    errors=input_manifest_errors(case)+validate_snapshot(case)
    length=duration(find_replay(case));errors+=subtitle_timing_errors(case,length)
    if rows[-1]['start_seconds']>length:errors.append('原稿时间超出回放')
    if errors:raise ValueError('；'.join(errors))
    labels=list(dict.fromkeys(b['label'] for b in rows))
    if participant_count is not None and (not isinstance(participant_count,int) or isinstance(participant_count,bool) or participant_count<3):raise ValueError('候选人数至少为三，仍须实际核对，不能作为声学结论')
    if (len(labels)<3 and participant_count is None) or any('未标注' in label for label in labels):
        raise ValueError('需要三个原标签，或以--participants提供本场已知的候选人数；未标注原稿须先建立可定位发言，不能伪造标签。')
    if local(case,META).exists():
        meta=read_json(local(case,META))
        if meta.get('binding')!=binding:raise ValueError('输入发生变化，不能重建索引掩盖差异')
        if layout and layout!=meta.get('layout'):raise ValueError('续作不能静默切换编辑方式')
        if not local(case,CLIPS).is_file() or not local(case,RECORD).is_file():raise ValueError('任务记录不完整，请保留现场核对')
        _check_clips(case,meta,read_json(local(case,CLIPS)))
        return {'status':'REUSED','case':str(case)}
    layout=layout or 'discussion'
    if layout not in ('discussion','sequential'):raise ValueError('未知多人版式')
    meta={'schema_version':1,'mode':'multi','layout':layout,'binding':binding,'duration_seconds':length,
          'source_blocks':[{k:b[k] for k in ('id','label','timecode','start_seconds','block_sha256','same_second')} for b in rows]}
    participants=[{'id':f'S{i}','display_name':f'发言者{i}','source_labels':[label],
                   'status':'pending','basis':'','first_source_id':'','review_ids':[]} for i,label in enumerate(labels,1)]
    for i in range(len(participants)+1,(participant_count or len(labels))+1):
        participants.append({'id':f'S{i}','display_name':f'发言者{i}','source_labels':[],'status':'pending','basis':'','first_source_id':'','review_ids':[]})
    record={'schema_version':1,'binding':binding,'title':'多人分享整理稿','participants':participants,
            'blocks':[{'id':b['id'],'source_label':b['label'],'speaker_ids':[], 'include':True,
                       'review_ids':[],'exclusion':None,'outline':{'topic':'','anchors':[]}} for b in rows],
            'reviews':[],'issues':[], 'full_draft':[], 'reading_draft':[],
            'whole_review':{'reviewer':'','finding':'','checks':[]}}
    for b in rows:
        if b['same_second']:
            record['issues'].append({'id':'I-'+b['id'],'priority':'P1','source_ids':[b['id']],
               'question':'同秒发言的边界与归属需核对；同秒不证明同时说话。','status':'pending','resolution':'','review_ids':[]})
    manifest={'schema_version':1,'binding':binding,'source_sha256':binding['replay_sha256'],'clips':[], 'samples':[], 'requirements':{}}
    folder=case/'_work/review_clips';folder.mkdir(parents=True,exist_ok=True)
    windows={}
    def add(reason,start,source_ids=()):
        start=min(max(0,float(start)),max(0,length-20));span=min(20,length-start)
        key=(round(start,6),round(span,6))
        if key not in windows:
            ident='M'+hashlib.sha256(f'{binding["replay_sha256"]}:{key}'.encode()).hexdigest()[:16]
            name=ident+'.m4a';out=local(case,Path('_work/review_clips')/name)
            if out.exists():raise FileExistsError('已有未绑定音频，保留现场，不覆盖')
            audio_clip(find_replay(case),out,start,span)
            if abs(duration(out)-span)>1:raise ValueError('提取音频的时长与请求不一致')
            item={'id':ident,'filename':name,'start':start,'duration':span,'audio_sha256':sha(out),
                  'timecode':f'{int(start)//60:02d}:{int(start)%60:02d}','source_ids':[],'reasons':[]}
            manifest['clips'].append(item);windows[key]=item
        item=windows[key]
        item['source_ids']=list(dict.fromkeys(item['source_ids']+list(source_ids)))
        item['reasons']=list(dict.fromkeys(item['reasons']+[reason.split(':')[0]]))
        manifest['requirements'][reason]=item['id']
        return item['id']
    for name,fraction in POSITIONS.items():add(name,length*fraction)
    first={}
    for b in rows:first.setdefault(b['label'],b)
    for b in first.values():add('first-appearance:'+b['id'],b['start_seconds']-3,[b['id']])
    for b in rows:
        if b['same_second']:add('same-second:'+b['id'],b['start_seconds']-3,[b['id']])
    # Persist only after all source-bound clips exist. Initialize uses an outer transaction.
    if bind(case)!=binding:raise ValueError('准备期间来源发生变化，不能写入核对记录')
    write_json(local(case,META),meta);write_json(local(case,CLIPS),manifest);write_json(local(case,RECORD),record)
    entry=['# 多人回听入口','','人物表和原标签仅为候选，以下片段尚未核对；请按实际听取或画面发现填写多人编辑记录。','']
    for c in manifest['clips']:
        excerpts=[b for b in rows if b['id'] in c['source_ids']]
        entry += [f'## {c["timecode"]} · {", ".join(c["reasons"])}','',f'[打开音频](review_clips/{c["filename"]})','',f'音频编号：`{c["id"]}`；窗口{c["start"]:g}–{c["start"]+c["duration"]:g}秒。','']
        for b in excerpts:entry += [f'{b["id"]} / {b["label"]}','', '> '+b['text'].replace('\n','\n> '),'']
    local(case,Path('_work/多人回听入口.md')).write_text('\n'.join(entry)+'\n',encoding='utf-8')
    return {'status':'NEEDS_REVIEW','participants_candidates':len(labels),'clips':len(manifest['clips'])}


@locked
def add_clip(case,block_id):
    case=Path(case).resolve();meta=read_json(local(case,META));manifest=read_json(local(case,CLIPS))
    if meta['binding']!=bind(case):raise ValueError('来源已变化')
    _check_clips(case,meta,manifest)
    b=next((b for b in source_blocks(case) if b['id']==block_id),None)
    if b is None:raise ValueError('未知原稿块编号')
    start=min(max(0,b['start_seconds']-3),max(0,meta['duration_seconds']-20));span=min(20,meta['duration_seconds']-start)
    # Retain prior reviews/files. Reuse a matching verified window.
    item=next((c for c in manifest['clips'] if abs(c['start']-start)<.001 and abs(c['duration']-span)<.001),None)
    if item is None:
        ident='M'+hashlib.sha256(f'{meta["binding"]["replay_sha256"]}:{(round(start,6),round(span,6))}'.encode()).hexdigest()[:16]
        path=local(case,Path('_work/review_clips')/(ident+'.m4a'))
        audio_clip(find_replay(case),path,start,span)
        item={'id':ident,'filename':path.name,'start':start,'duration':span,'audio_sha256':sha(path),'timecode':b['timecode'],'source_ids':[],'reasons':['requested']}
        manifest['clips'].append(item)
    item['source_ids']=list(dict.fromkeys(item['source_ids']+[block_id]))
    manifest['requirements']['requested:'+block_id]=item['id']
    write_json(local(case,CLIPS),manifest)
    return {'clip_id':item['id'],'path':str(local(case,Path('_work/review_clips')/item['filename']))}


def _check_clips(case,meta,manifest):
    if manifest.get('binding')!=meta['binding'] or manifest.get('source_sha256')!=meta['binding']['replay_sha256']:raise ValueError('音频清单与来源不匹配')
    clips=manifest.get('clips',[])
    if not isinstance(clips,list) or not clips:raise ValueError('缺少核对音频')
    ids=set()
    for c in clips:
        if c['id'] in ids:raise ValueError('音频编号重复')
        ids.add(c['id']);name=c['filename']
        if Path(name).name!=name:raise ValueError('音频文件名越界')
        path=local(case,Path('_work/review_clips')/name)
        if not path.is_file() or sha(path)!=c['audio_sha256']:raise ValueError('核对音频已变化')
        a,b=c['start'],c['duration']
        if any(not isinstance(n,(int,float)) or isinstance(n,bool) or not math.isfinite(n) for n in (a,b)) or a<0 or b<=0 or a+b>meta['duration_seconds']+.01:
            raise ValueError('核对窗口超出原回放')
        if abs(duration(path)-b)>1:raise ValueError('核对音频时长不匹配')
    req=manifest.get('requirements',{})
    rows=source_blocks(case);first={}
    for b in rows:first.setdefault(b['label'],b)
    for name,fraction in POSITIONS.items():
        c=next((c for c in clips if c['id']==req.get(name)),None)
        expected=min(max(0,meta['duration_seconds']-20),meta['duration_seconds']*fraction)
        if c is None or abs(c['start']-expected)>.01 or abs(c['duration']-min(20,meta['duration_seconds']-expected))>.01:raise ValueError('缺少真实五位置核对窗口')
    for name,b in [('first-appearance',b) for b in first.values()]+[('same-second',b) for b in rows if b['same_second']]:
        c=next((c for c in clips if c['id']==req.get(name+':'+b['id'])),None)
        if c is None or b['id'] not in c['source_ids'] or not c['start']<=b['start_seconds']<c['start']+c['duration']:
            raise ValueError('缺少人物首次出场或同秒片段')
    if any(v not in ids for v in req.values()):raise ValueError('核对要求指向不存在的音频')
    return {c['id']:c for c in clips}


def norm(s):return ''.join(re.findall(r'[\w\u4e00-\u9fff]',s)).lower()
def recall(source,target):
    c=Counter(norm(source));n=sum(c.values())
    return sum((c & Counter(norm(target))).values())/n if n else 1.0


def inspect(case):
    case=Path(case).resolve();errors=[];warnings=[];metrics={}
    try:
        meta=read_json(local(case,META));record=read_json(local(case,RECORD));rows=source_blocks(case)
        errors+=input_manifest_errors(case)+validate_snapshot(case)
        current=bind(case)
        if meta.get('mode')!='multi' or meta.get('schema_version')!=1 or record.get('schema_version')!=1:raise ValueError('多人任务格式无效')
        if meta.get('binding')!=current or record.get('binding')!=current:raise ValueError('多人记录与当前来源不一致')
        expected=[{k:b[k] for k in ('id','label','timecode','start_seconds','block_sha256','same_second')} for b in rows]
        if meta.get('source_blocks')!=expected:raise ValueError('原稿索引缺失、重排或变化')
        if abs(duration(find_replay(case))-meta['duration_seconds'])>.05:raise ValueError('来源时长不一致')
        errors+=subtitle_timing_errors(case,meta['duration_seconds'])
        manifest=read_json(local(case,CLIPS));clips=_check_clips(case,meta,manifest)
        reviews={}
        for r in record.get('reviews',[]):
            if r['clip_id'] in reviews:raise ValueError('同一音频核对记录重复')
            if r['clip_id'] not in clips or not all(nonblank(r.get(k)) for k in ('method','reviewer','finding')):raise ValueError('核对记录不完整')
            if not re.search(r'真人回听|音频理解|回放画面',r['method']) or re.search(r'待|未|计划|准备|转写文本|原稿标签',r['method']):raise ValueError('需要实际原声或画面的核对记录')
            checked=r.get('checked_source_ids',[])
            if not isinstance(checked,list) or len(checked)!=len(set(checked)) or any(x not in clips[r['clip_id']]['source_ids'] for x in checked):raise ValueError('核对记录的原文范围超出片段绑定')
            reviews[r['clip_id']]=r
        for reason,ident in manifest['requirements'].items():
            if ident not in reviews:errors.append('核对音频尚未实际确认：'+ident)
            elif ':' in reason and reason.split(':',1)[1] not in reviews[ident].get('checked_source_ids',[]):errors.append('本原文位置尚未实际核对：'+reason)
        def reviewed(ids,block=None):
            return isinstance(ids,list) and bool(ids) and all(x in reviews for x in ids) and (block is None or any(block in clips[x]['source_ids'] and block in reviews[x].get('checked_source_ids',[]) for x in ids if x in clips))
        participants=record.get('participants',[])
        if not isinstance(participants,list) or len(participants)<3:raise ValueError('多人流程需要至少三位经核对的参与者，不以原标签数量代替实际人数')
        people={};label_map={}
        for p in participants:
            ident=p.get('id','');name=p.get('display_name','')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,40}',ident) or ident in people or not nonblank(name) or '\n' in name:raise ValueError('人物编号或显示名称无效')
            if name in {x['display_name'] for x in people.values()}:raise ValueError('同名人物须加角色等区分显示')
            people[ident]=p
            if p.get('status')!='confirmed' or not nonblank(p.get('basis')):errors.append('人物声音/称谓尚未确认：'+ident)
            if not isinstance(p.get('source_labels'),list):raise ValueError('人物原标签线索格式无效')
            if not p['source_labels']:
                anchor=p.get('first_source_id')
                if anchor not in {b['id'] for b in rows} or not reviewed(p.get('review_ids'),anchor):errors.append('无独立原标签的人物缺少首次发言核对：'+ident)
            for label in p['source_labels']:
                if label in label_map:raise ValueError('同一原标签不能默认映射到多位人物；须逐块核对')
                label_map[label]=ident
                first=next((b for b in rows if b['label']==label),None)
                if first is None or not reviewed(p.get('review_ids'),first['id']):errors.append('人物首次出场缺少实际核对：'+ident)
        if set(label_map)!={b['label'] for b in rows}:raise ValueError('人物表未覆盖当前所有原标签')
        blocks=record.get('blocks',[])
        if not isinstance(blocks,list) or [b.get('id') for b in blocks]!=[b['id'] for b in rows]:raise ValueError('逐块记录缺失、重复或重排')
        mapped={};source={b['id']:b for b in rows}
        for b,raw in zip(blocks,rows):
            if b.get('source_label')!=raw['label'] or not isinstance(b.get('include'),bool):raise ValueError('逐块来源标签或处理状态无效')
            speakers=b.get('speaker_ids',[])
            if not isinstance(speakers,list) or not speakers or len(set(speakers))!=len(speakers) or any(s not in people for s in speakers):errors.append('原稿发言归属尚未确认：'+b['id'])
            if speakers!=[label_map[raw['label']]] and not reviewed(b.get('review_ids'),b['id']):errors.append('标签冲突/混合发言缺少逐块核对：'+b['id'])
            if raw['same_second'] and not reviewed(b.get('review_ids'),b['id']):errors.append('同秒发言缺少边界核对：'+b['id'])
            if not b['include']:
                ex=b.get('exclusion') or {}
                if ex.get('category') not in ('filler','operations','off-topic') or not all(nonblank(ex.get(k)) for k in ('reason','confirmed_by')) or not reviewed(ex.get('review_ids'),b['id']):errors.append('排除内容缺少分类、原因及实际核对：'+b['id'])
            mapped[b['id']]=b
        drafts={}
        for key in ('full_draft','reading_draft'):
            segs=record.get(key,[])
            if not isinstance(segs,list) or not segs:errors.append('缺少完整底稿或阅读稿：'+key);drafts[key]=[];continue
            seen=set();last=-1
            for seg in segs:
                ident=seg.get('id','');refs=seg.get('source_ids',[]);speaker=seg.get('speaker_id')
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,40}',ident) or ident in seen or not nonblank(seg.get('text')):raise ValueError('编辑段落编号或正文无效')
                seen.add(ident)
                if not isinstance(refs,list) or not refs or len(set(refs))!=len(refs) or any(x not in mapped for x in refs):raise ValueError('编辑段落缺少有效来源')
                indices=[source[x]['ordinal'] for x in refs]
                if indices!=sorted(indices) or min(indices)<last:errors.append('编辑段落改变发言先后：'+ident)
                last=max(indices)
                for x in refs:
                    if not mapped[x]['include'] or speaker not in mapped[x]['speaker_ids']:errors.append('编辑段落串人或使用已排除内容：'+ident)
                origin='\n'.join(source[x]['text'] for x in refs)
                if not set(re.findall(r'\d+(?:\.\d+)?',seg['text'])).issubset(set(re.findall(r'\d+(?:\.\d+)?',origin))):errors.append('编辑段落出现来源没有的数字：'+ident)
                if recall(seg['text'],origin)<.65:errors.append('编辑段落新增内容过多，须对照来源：'+ident)
            drafts[key]=segs
        per_person={}
        for ident,p in people.items():
            full=''.join(s['text'] for s in drafts['full_draft'] if s['speaker_id']==ident)
            reading=''.join(s['text'] for s in drafts['reading_draft'] if s['speaker_id']==ident)
            active=any(b['include'] and ident in b['speaker_ids'] for b in blocks)
            if active and (not full or not reading):errors.append('人物在完整底稿或阅读稿中被遗漏：'+ident)
            rate=recall(full,reading)
            if rate<.90:errors.append('阅读稿过度压缩某位人物的有效底稿：'+ident)
            per_person[ident]={'name':p['display_name'],'full_chars':len(norm(full)),'reading_chars':len(norm(reading)),'reading_to_full_overlap':round(rate,4)}
        for ident,b in mapped.items():
            if not b['include']:continue
            for who in b['speaker_ids']:
                full=''.join(s['text'] for s in drafts['full_draft'] if ident in s['source_ids'] and s['speaker_id']==who)
                reading=''.join(s['text'] for s in drafts['reading_draft'] if ident in s['source_ids'] and s['speaker_id']==who)
                if not full or not reading:errors.append('有效发言在底稿或阅读稿中缺失：'+ident)
                if len(b['speaker_ids'])==1 and (recall(source[ident]['text'],full)<.70 or recall(source[ident]['text'],reading)<.60):errors.append('有效原稿块被过度压缩：'+ident)
            outline=b.get('outline',{})
            anchors=outline.get('anchors',[])
            if not nonblank(outline.get('topic')) or not isinstance(anchors,list) or not anchors:errors.append('缺少通读全场后的内容盘点：'+ident)
            for anchor in anchors:
                quote=anchor.get('quote','');kind=anchor.get('kind')
                if kind not in ('point','example','limit','question','opposition','ending','number') or not nonblank(quote) or quote not in source[ident]['text']:
                    errors.append('内容盘点缺少真实原句：'+ident);continue
                selected=''.join(seg['text'] for seg in drafts['reading_draft'] if ident in seg['source_ids'])
                if (kind in ('limit','opposition','number') and norm(quote) not in norm(selected)) or recall(quote,selected)<.85:errors.append('关键观点、例子或限制未保留：'+ident)

        issue_ids=set();open_p1=0
        for issue in record.get('issues',[]):
            ident=issue.get('id');refs=issue.get('source_ids',[])
            if not isinstance(ident,str) or not ident or ident in issue_ids or issue.get('priority') not in ('P0','P1','P2') or not nonblank(issue.get('question')):raise ValueError('待核问题编号、级别或问题无效')
            issue_ids.add(ident)
            if not isinstance(refs,list) or not refs or any(x not in mapped for x in refs):raise ValueError('待核问题缺少原文定位')
            if issue.get('status') not in ('pending','resolved','conservative'):raise ValueError('待核问题状态无效')
            if issue['priority'] in ('P0','P1') and any(not any(x in c['source_ids'] for c in clips.values()) for x in refs):errors.append('重要待核项缺少可打开的原声：'+ident)
            if issue['status']!='pending':
                adopted=issue.get('adopted_text','')
                current_text='\n'.join(s['text'] for s in drafts['reading_draft'] if set(refs)&set(s['source_ids']))
                if not nonblank(issue.get('resolution')) or any(not reviewed(issue.get('review_ids'),x) for x in refs) or not nonblank(adopted) or adopted not in current_text:errors.append('关闭问题或保守改写缺少实际核对与采用写法：'+ident)
            if issue['status']=='pending':
                if issue['priority']=='P0':errors.append('P0问题尚未解决：'+ident)
                elif issue['priority']=='P1':open_p1+=1;warnings.append('P1待核：'+ident)
        whole=record.get('whole_review',{})
        if not all(nonblank(whole.get(k)) for k in ('reviewer','finding')) or set(whole.get('checks',[]))!=set(EDITOR_CHECKS):errors.append('缺少从原稿逐项反查与全稿通读记录')
        metrics={'participants':per_person,'source_blocks':len(rows),'excluded_blocks':sum(not b['include'] for b in blocks),'open_p1':open_p1,'reviewed_clips':len(reviews),'independent_audio_windows':len(clips)}
        return errors,warnings,metrics,(meta,record,rows,manifest)
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
        return errors+[str(exc)],warnings,metrics,None


def documents(case,context,metrics):
    meta,r,rows,m=context;people={p['id']:p for p in r['participants']}
    def draft(segs):
        lines=['# '+r.get('title','多人分享整理稿'),'']
        previous=None
        for s in segs:
            name=people[s['speaker_id']]['display_name']
            if meta['layout']=='sequential':
                if previous!=s['speaker_id']:lines+=['## '+name,'']
                lines+=['<!-- multi:'+s['id']+' -->',s['text'],'']
            else:lines+=['<!-- multi:'+s['id']+' -->','**'+name+'：** '+s['text'],'']
            previous=s['speaker_id']
        return '\n'.join(lines)+'\n'
    index=['# 待核原文索引','','本页是原稿定位副本，原始文件保持只读。','']
    for b in rows:index += ['<a id="'+b['id'].lower()+'"></a>','## '+b['timecode']+' · '+b['label'],'','> '+b['text'].replace('\n','\n> '),'']
    audio=['# 回听辅助索引','','以下音频只用于核对；是否实际听取以真实核对记录为准。','']
    for c in m['clips']:audio += [f'- {c["timecode"]} / {", ".join(c["reasons"])}：[打开音频](review_clips/{c["filename"]})','']
    issues=['# 待核对清单','','本清单依据原文位置列出问题。完整稿仍须人工审核。','']
    by_id={b['id']:b for b in rows};clip_by_id={c['id']:c for c in m['clips']}
    for issue in r['issues']:
        issues += ['## '+issue['priority']+' · '+issue['question'],'','状态：'+issue['status'],'']
        for ident in issue['source_ids']:
            b=by_id[ident]
            issues += [f'- [{b["timecode"]} · {b["label"]}](../_work/待核原文索引.md#{ident.lower()})','> '+b['text'].replace('\n','\n> '),'']
            clips=[c for c in m['clips'] if ident in c['source_ids']]
            for c in clips:issues += [f'[打开对应原声](../_work/review_clips/{c["filename"]})','']
            current='\n'.join(s['text'] for s in r['reading_draft'] if ident in s['source_ids'])
            issues += ['当前稿：'+(current or '未使用，见编辑记录。'),'']
        if issue.get('resolution'):issues += ['核对结论／采用写法：'+issue['resolution'],'']
    if not r['issues']:issues+=['本轮未列出待核疑点；不代表所有事实已经独立核实。','']
    report=['# 编辑质检报告','','状态：生成时技术包检查通过；人工终审情况以绑定本稿的真实记录为准。',
            '检查只能验证来源绑定、覆盖及核对记录结构，不能证明记录中的听取或审校真实发生。','',
            '版式：'+meta['layout'],'','| 人物 | 完整底稿字数 | 阅读稿字数 | 阅读稿对底稿字词覆盖 |','| --- | ---: | ---: | ---: |']
    for p in metrics['participants'].values():report.append(f'| {p["name"]} | {p["full_chars"]} | {p["reading_chars"]} | {p["reading_to_full_overlap"]:.1%} |')
    report+=['','字词比例只用于发现异常，不证明观点、否定或限制条件全部保留。','',f'未关闭P1：{metrics["open_p1"]}。人工终审以绑定本次稿件的真实记录为准。','']
    result={MAIN:draft(r['reading_draft']),Path('_work/完整编辑底稿.md'):draft(r['full_draft']),ISSUES:'\n'.join(issues)+'\n',REPORT:'\n'.join(report)+'\n',Path('_work/待核原文索引.md'):'\n'.join(index)+'\n',Path('_work/回听辅助索引.md'):'\n'.join(audio)+'\n'}
    binding=meta['binding']
    def encoded(data):return json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    result[Path('_work/证据映射.json')]=encoded({'schema':'multi-v1','binding':binding,'full_draft':r['full_draft'],'reading_draft':r['reading_draft']})
    result[Path('_work/编辑决策台账.json')]=encoded({'schema':'multi-v1','binding':binding,'blocks':r['blocks'],'issues':r['issues'],'whole_review':r['whole_review']})
    result[Path('_work/说话人校准.json')]=encoded({'schema':'multi-v1','binding':binding,'participants':r['participants'],'note':'实际核对记录见多人编辑记录；原标签仅为线索，不运行双人声音聚类。'})
    result[Path('_work/说话人时间轴.json')]=encoded({'schema':'multi-v1','binding':binding,'turns':[{'source_block_id':b['id'],'source_start':b['timecode'],'same_second':b['same_second'],'source_label':b['label'],'speaker_ids':r['blocks'][i]['speaker_ids'],'review_ids':r['blocks'][i]['review_ids']} for i,b in enumerate(rows)]})
    result[Path('_work/场次分流.json')]=encoded({'schema':'multi-v1','mode':'multi','status':'PASS','binding':binding,'reviewed_participant_count':len(people),'target_skill':'references/multi.md','note':'人物核对记录与当前来源绑定；不是自动声学人数识别，不接受旧版单/双人审计替代。'})
    coverage=['# 内容覆盖表','','| 原文位置 | 话题 | 人物 | 底稿段落 | 阅读稿段落 | 处理 |','| --- | --- | --- | --- | --- | --- |']
    conflicts=['# 说话人冲突清单','','同秒只是时间线索，是否重叠与谁在说话以实际核对为准。','']
    for i,b in enumerate(rows):
        row=r['blocks'][i]
        full_ids=','.join(x['id'] for x in r['full_draft'] if b['id'] in x['source_ids'])
        read_ids=','.join(x['id'] for x in r['reading_draft'] if b['id'] in x['source_ids'])
        topic=row.get('outline',{}).get('topic','').replace('|','／').replace('\n',' ')
        names='、'.join(people[x]['display_name'] for x in row['speaker_ids'])
        coverage.append(f'| {b["timecode"]} / {b["id"]} | {topic} | {names} | {full_ids} | {read_ids} | {"保留" if row["include"] else "核对后排除"} |')
        if b['same_second'] or len(row['speaker_ids'])!=1 or not all(b['label'] in people[x]['source_labels'] for x in row['speaker_ids']):
            conflicts += [f'- {b["timecode"]} / {b["id"]}：{b["label"]} → {names}；核对片段：'+','.join(row['review_ids']),'']
    if len(conflicts)==4:conflicts+=['本轮未登记标签冲突；不代表原标签天然正确。','']
    result[Path('_work/内容覆盖表.md')]='\n'.join(coverage)+'\n'
    result[Path('_work/说话人冲突清单.md')]='\n'.join(conflicts)+'\n'
    terminal=['# 回听终审表','','此表只列事实核对状态；人工发布终审另以多人终审记录为准。','']
    for issue in r['issues']:terminal += [f'- {issue["id"]} / {issue["priority"]}：{issue["status"]}；'+issue.get('resolution',''),'']
    if not r['issues']:terminal+=['本轮没有列出的疑点，仍须通读和人工终审。','']
    result[Path('_work/回听终审表.md')]='\n'.join(terminal)+'\n'
    return result



@locked
def render(case):
    case=Path(case).resolve();errors,warnings,metrics,context=inspect(case)
    if errors:raise ValueError('；'.join(errors))
    payloads=documents(case,context,metrics)
    previous=read_json(local(case,GENERATED)).get('files',{}) if local(case,GENERATED).exists() else {}
    for rel,body in payloads.items():
        path=local(case,rel)
        if path.exists() and path.read_text()!=body and previous.get(rel.as_posix())!=sha(path):raise FileExistsError('已有人工修改，保留不覆盖：'+rel.as_posix())
    for rel,body in payloads.items():
        path=local(case,rel);path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists() or path.read_text()!=body:path.write_text(body,encoding='utf-8')
    write_json(local(case,GENERATED),{'schema_version':1,'record_sha256':sha(local(case,RECORD)), 'files':{rel.as_posix():sha(local(case,rel)) for rel in payloads}})
    return audit(case)


def audit(case,*,release=False):
    case=Path(case).resolve();errors,warnings,metrics,context=inspect(case)
    if not errors:
        try:
            generated=read_json(local(case,GENERATED))
            if generated.get('record_sha256')!=sha(local(case,RECORD)):raise ValueError('编辑记录更新后尚未重新生成文稿')
            expected=documents(case,context,metrics)
            if set(generated.get('files',{}))!={p.as_posix() for p in expected}:raise ValueError('交付清单不完整')
            for rel,body in expected.items():
                path=local(case,rel)
                if not path.is_file() or path.read_text()!=body or generated['files'].get(rel.as_posix())!=sha(path):errors.append('交付与本次编辑记录不一致：'+rel.as_posix())
            if release:
                if metrics['open_p1']:errors.append('发布前仍有未关闭P1')
                receipt=read_json(local(case,HUMAN))
                if receipt.get('decision')!='approved' or not all(nonblank(receipt.get(k)) for k in ('reviewer','reviewed_at','basis')) or receipt.get('draft_sha256')!=sha(local(case,MAIN)) or receipt.get('record_sha256')!=sha(local(case,RECORD)):
                    errors.append('缺少绑定当前稿件与编辑记录的真实人工终审')
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc))
    return {'status':'BLOCKED' if errors else 'PASS','mode':'multi','errors':list(dict.fromkeys(errors)),'warnings':warnings,'metrics':metrics,
            'release_ready':bool(release and not errors),'note':'技术检查不证明实际听取或真人终审发生；不得由工具代填核对事实。'}


@locked
def export(case,destination):
    result=audit(case)
    if result['errors']:raise ValueError('交付检查未通过：'+'；'.join(result['errors']))
    return {'path':str(export_outputs(Path(case),Path(destination))),'human_final_review':'导出不代表人工终审或对外发布'}


def main():
    parser=argparse.ArgumentParser(description='已有多人转写稿与回放的整理、核对和交付')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init');p.add_argument('--case',type=Path,required=True);p.add_argument('--replay',type=Path,required=True);p.add_argument('--transcript',type=Path,required=True);p.add_argument('--layout',choices=['discussion','sequential'],required=True);p.add_argument('--profile',type=Path);p.add_argument('--participants',type=int)
    for name in ('prepare','render','audit'):
        p=sub.add_parser(name);p.add_argument('case',type=Path)
        if name=='audit':p.add_argument('--release',action='store_true')
    p=sub.add_parser('clip');p.add_argument('case',type=Path);p.add_argument('--block',required=True)
    p=sub.add_parser('export');p.add_argument('case',type=Path);p.add_argument('destination',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='init':result=initialize(args.case,args.replay,args.transcript,layout=args.layout,profile=args.profile,participant_count=args.participants)
        elif args.command=='prepare':result=prepare(args.case)
        elif args.command=='clip':result=add_clip(args.case,args.block)
        elif args.command=='render':result=render(args.case)
        elif args.command=='export':result=export(args.case,args.destination)
        else:result=audit(args.case,release=args.release)
        print(json.dumps(result,ensure_ascii=False,indent=2,default=str));return 1 if result.get('status')=='BLOCKED' else 0
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
