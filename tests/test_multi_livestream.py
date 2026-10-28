"""Controlled structural fixtures, not real listening or manuscript-quality acceptance."""
import copy
import importlib.util
import json
import re
from urllib.parse import unquote,urlsplit
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import multi_livestream as multi


class MultiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.shared.cleanup)
        cls.media=Path(cls.shared.name)/'synthetic.m4a'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','260','-c:a','aac',str(cls.media)],check=True)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.case=self.root/'case'

    def make_case(self,n=3,tied=False,end_late=False,ops_third=False):
        texts=['我先讲产品测试。我们上个月访谈了十二位用户，先记录问题，再分别验证，暂时不能推断所有用户都需要这个功能。',
               '我补充课程运营。学员完成作业以后，我们会逐条反馈具体问题，而不是只给一个分数，再让他们自己猜怎么改。',
               '我不同意直接增加投放。先检查文章的阅读和报名反馈，再决定预算，不能把阅读量直接当成实际成交。',
               '我分享团队协作。我们把每次修改的原因留下，交接时一起核对，让后加入的同事知道当时为什么这样决定。',
               '我想追问访谈的范围。这里说的是已经使用产品的人，还是第一次接触的人，两类情况应该分别记录和比较。',
               '我补充最后的安排。先完成小范围验证，再集中回顾结果，确认问题解决后才推进下一步，不能跳过检查。']
        if ops_third:texts[2]='请稍等，我只确认麦克风是否打开，接下来由其他嘉宾继续分享。'
        times=[i*20 for i in range(n*2)]
        if tied:times[1]=times[0]
        if end_late:times[-1]=250
        source=self.root/'source.md'
        source.write_text('\n\n'.join(f'发言人{i%n+1}  {t//60:02d}:{t%60:02d}\n{texts[i%n]}' for i,t in enumerate(times)))
        multi.initialize(self.case,self.media,source,layout='discussion')
        return source

    def ready(self):
        record=multi.read_json(self.case/multi.RECORD)
        manifest=multi.read_json(self.case/multi.CLIPS)
        # Simulated review inputs solely for positive/negative structural tests.
        record['reviews']=[{'clip_id':c['id'],'method':'真人回听','reviewer':'合成夹具-非真人验收','finding':'合成测试：核对本片段发言归属与文字，非真实声音结论。','checked_source_ids':list(c['source_ids'])} for c in manifest['clips']]
        first={}
        for b in record['blocks']:first.setdefault(b['source_label'],b['id'])
        for p in record['participants']:
            p['status']='confirmed';p['basis']='合成测试的预设人物表，不代表真实身份。'
            p['review_ids']=[c['id'] for c in manifest['clips'] if (first[p['source_labels'][0]] if p['source_labels'] else p['first_source_id']) in c['source_ids']]
        for b in record['blocks']:
            p=next(p for p in record['participants'] if b['source_label'] in p['source_labels'])
            b['speaker_ids']=[p['id']]
            b['outline']={'topic':'合成内容盘点','anchors':[{'kind':'point','quote':next(x['text'] for x in multi.source_blocks(self.case) if x['id']==b['id'])}]}
            b['review_ids']=[c['id'] for c in manifest['clips'] if b['id'] in c['source_ids']]
        source={b['id']:b for b in multi.source_blocks(self.case)}
        record['full_draft']=[{'id':f'D{i:04d}','speaker_id':b['speaker_ids'][0],'source_ids':[b['id']],'text':source[b['id']]['text']} for i,b in enumerate(record['blocks'],1)]
        record['reading_draft']=copy.deepcopy(record['full_draft'])
        record['whole_review']={'reviewer':'合成夹具-非真人终审','finding':'结构测试逐项核对，不构成真实素材质量验收。','checks':list(multi.EDITOR_CHECKS)}
        multi.write_json(self.case/multi.RECORD,record)
        return record

    def save(self,r):multi.write_json(self.case/multi.RECORD,r)

    def test_three_and_six_people_keep_every_voice_and_export(self):
        for n in (3,6):
            if self.case.exists():self.case=self.root/f'case-{n}'
            original=self.make_case(n);before=original.read_bytes();self.ready()
            multi.render(self.case)
            result=multi.audit(self.case)
            self.assertEqual(result['status'],'PASS',result)
            self.assertFalse(result['release_ready'])
            self.assertEqual(len(result['metrics']['participants']),n)
            main=(self.case/multi.MAIN).read_text()
            for i in range(1,n+1):self.assertIn(f'发言者{i}',main)
            self.assertEqual(original.read_bytes(),before)
            dest=self.root/f'export-{n}'
            multi.export(self.case,dest)
            self.assertTrue((dest/'01_公众号可发布稿.md').is_file())
            self.assertTrue((dest/'02_待核问题清单.md').is_file())
            for doc in dest.rglob('*.md'):
                for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
                    url=urlsplit(target)
                    if not url.scheme and url.path:self.assertTrue((doc.parent/unquote(url.path)).is_file(),(doc,target))

    def test_pending_observations_are_not_silently_confirmed(self):
        self.make_case()
        r=multi.audit(self.case)
        self.assertEqual(r['status'],'BLOCKED')
        self.assertTrue(any('核对' in x or '确认' in x for x in r['errors']))
        with self.assertRaises(ValueError):multi.render(self.case)

    def test_late_person_gets_first_appearance_clip(self):
        source=self.root/'late.md'
        source.write_text('发言人1  00:00\n先介绍本次讨论。\n\n发言人2  01:00\n分享团队协作。\n\n发言人3  03:59\n我最后补充一项建议。')
        multi.initialize(self.case,self.media,source,layout='discussion')
        m=multi.read_json(self.case/multi.CLIPS)
        rows=multi.source_blocks(self.case)
        first=next(b for b in rows if b['label']=='发言人3')
        self.assertTrue(any(first['id'] in c['source_ids'] and 'first-appearance' in c['reasons'] for c in m['clips']))
        self.assertTrue(all(x in m['requirements'] for x in ['opening','quarter','middle','three-quarter','ending']))

    def test_third_person_cannot_be_absorbed_into_second(self):
        self.make_case();r=self.ready()
        third=next(b for b in r['blocks'] if b['source_label']=='发言人3')
        third['speaker_ids']=['S2'];self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_delete_one_person_or_move_their_words_fails(self):
        self.make_case();r=self.ready()
        r['reading_draft']=[s for s in r['reading_draft'] if s['speaker_id']!='S3'];self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')
        r=self.ready();r['reading_draft'][0]['speaker_id']='S2';self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_same_second_ids_preserved_and_need_specific_review(self):
        self.make_case(tied=True);r=self.ready()
        self.assertEqual(len({b['id'] for b in r['blocks']}),len(r['blocks']))
        r['blocks'][0]['review_ids']=[];self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')
        self.ready();multi.render(self.case)
        self.assertEqual(multi.audit(self.case)['status'],'PASS')

    def test_unreviewed_exclusion_is_not_a_coverage_shortcut(self):
        self.make_case();r=self.ready();r['blocks'][0]['include']=False
        r['blocks'][0]['exclusion']={'reason':'为了缩短','review_ids':[]}
        self.save(r);self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_changed_media_or_clip_cannot_reuse_review(self):
        self.make_case();self.ready()
        m=multi.read_json(self.case/multi.CLIPS)
        (self.case/'_work/review_clips'/m['clips'][0]['filename']).write_bytes(b'tampered')
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_changed_source_is_not_reindexed_to_hide_it(self):
        self.make_case();p=self.case/multi.SOURCE;p.write_text(p.read_text()+'\n新增文字')
        with self.assertRaises(ValueError):multi.prepare(self.case)

    def test_manual_draft_is_not_overwritten(self):
        self.make_case();self.ready();multi.render(self.case)
        p=self.case/multi.MAIN;p.write_text('真人改稿')
        with self.assertRaises(FileExistsError):multi.render(self.case)
        self.assertEqual(p.read_text(),'真人改稿')
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_release_requires_current_human_receipt_and_closed_issues(self):
        self.make_case();self.ready();multi.render(self.case)
        self.assertEqual(multi.audit(self.case,release=True)['status'],'BLOCKED')
        receipt={'reviewer':'合成夹具-不代表真实终审','decision':'approved','reviewed_at':'2000-01-01T00:00:00Z (synthetic fixture)','basis':'模拟测试输入','draft_sha256':multi.sha(self.case/multi.MAIN),'record_sha256':multi.sha(self.case/multi.RECORD)}
        multi.write_json(self.case/multi.HUMAN,receipt)
        self.assertEqual(multi.audit(self.case,release=True)['status'],'PASS')
        r=multi.read_json(self.case/multi.RECORD);r['whole_review']['finding']+=' changed';self.save(r);multi.render(self.case)
        self.assertEqual(multi.audit(self.case,release=True)['status'],'BLOCKED')

    def test_new_numbers_and_empty_claims_do_not_pass(self):
        self.make_case();r=self.ready();r['reading_draft'][0]['text']+='新增9999人购买。';self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')
        r=self.ready();r['whole_review']['checks']=[];self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_resume_preserves_record_and_reuses_clips(self):
        self.make_case();self.ready();before=(self.case/multi.RECORD).read_bytes()
        m=multi.read_json(self.case/multi.CLIPS)
        stamps={c['filename']:(self.case/'_work/review_clips'/c['filename']).stat().st_mtime_ns for c in m['clips']}
        multi.prepare(self.case)
        self.assertEqual(before,(self.case/multi.RECORD).read_bytes())
        self.assertEqual(stamps,{c['filename']:(self.case/'_work/review_clips'/c['filename']).stat().st_mtime_ns for c in m['clips']})


    def test_sequential_layout_and_pre_review_entry(self):
        self.make_case()
        self.assertTrue((self.case/'_work/多人回听入口.md').is_file())
        meta=multi.read_json(self.case/multi.META);meta['layout']='sequential';multi.write_json(self.case/multi.META,meta)
        self.ready();multi.render(self.case)
        self.assertIn('## 发言者1',(self.case/multi.MAIN).read_text())

    def test_discussion_joins_adjacent_verified_same_person_labels_without_losing_sources(self):
        self.make_case();r=self.ready()
        first=r['reading_draft'][0]
        split=first['text'].index('。')+1
        second=copy.deepcopy(first)
        first['text'],second['text']=first['text'][:split],first['text'][split:]
        second['id']='D0001-second'
        r['reading_draft'].insert(1,second)
        self.save(r);multi.render(self.case)
        text=(self.case/multi.MAIN).read_text()
        self.assertIn(first['text'],text);self.assertIn(second['text'],text)
        self.assertEqual(text.count('**发言者1：**'),2)
        self.assertIn('<!-- multi:D0001-second -->',text)

    def test_multi_review_uses_shared_table_shape_preserving_each_issue_and_resolution(self):
        self.make_case();r=self.ready();block=r['blocks'][0]
        r['issues']=[{'id':'PENDING','priority':'P2','source_ids':[block['id']],
                      'question':'模拟：核对提问范围','status':'pending'},
                     {'id':'SAFE','priority':'P1','source_ids':[block['id']],
                      'question':'模拟：核对用户数量','status':'conservative',
                      'resolution':'合成夹具结论，非真实回听',
                      'adopted_text':r['reading_draft'][0]['text'],
                      'review_ids':block['review_ids']}]
        self.save(r);multi.render(self.case)
        text=(self.case/multi.ISSUES).read_text()
        self.assertIn('| 级别 | 时间码 | 问题类型 | 原文/成稿 | 处理建议 | 状态 |',text)
        lines=[line for line in text.splitlines() if line.startswith('| P')]
        self.assertEqual(len(lines),2)
        self.assertIn('SAFE',lines[0]);self.assertIn('PENDING',lines[1])
        self.assertIn('合成夹具结论，非真实回听',text)
        self.assertIn('已保守表达',text)
        self.assertIn('../_work/待核原文索引.md#',text)

    def test_same_audio_review_does_not_confirm_a_new_source_block(self):
        self.make_case(end_late=True);r=self.ready()
        target=r['blocks'][-1]['id']
        result=multi.add_clip(self.case,target)
        self.assertIn(result['clip_id'],[x['clip_id'] for x in r['reviews']])
        r=multi.read_json(self.case/multi.RECORD)
        # This is a newly requested check, even if the audio window can be reused.
        self.save(r)
        self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')

    def test_current_draft_must_match_closed_issue_adoption(self):
        self.make_case();r=self.ready();block=r['blocks'][0]
        r['issues']=[{'id':'FACT1','priority':'P1','source_ids':[block['id']],
                     'question':'测试疑点','status':'conservative','resolution':'合成核对结论',
                     'review_ids':block['review_ids'],'adopted_text':'正文不存在的保守写法'}]
        self.save(r);self.assertEqual(multi.audit(self.case)['status'],'BLOCKED')



    def test_non_contiguous_merge_cannot_reorder_other_people(self):
        self.make_case();r=self.ready()
        r['reading_draft'][0]['source_ids']=[r['blocks'][0]['id'],r['blocks'][3]['id']]
        r['reading_draft'][0]['text']+=r['reading_draft'][3]['text']
        self.save(r)
        self.assertTrue(any('先后' in x for x in multi.audit(self.case)['errors']))



    def test_merged_source_label_can_be_corrected_without_rewriting_original(self):
        text='\n\n'.join(f'发言人{label}  {i*20//60:02d}:{i*20%60:02d}\n第{i+1}段分享保留具体问题、方法、例子和限制条件，不能把不同人的观点拼接在一起。' for i,label in enumerate([1,2,1,1,2,1]))
        source=self.root/'merged.md';source.write_text(text)
        multi.initialize(self.case,self.media,source,layout='discussion',participant_count=3)
        record=multi.read_json(self.case/multi.RECORD)
        targets=[record['blocks'][i]['id'] for i in (2,5)]
        record['participants'][2]['first_source_id']=targets[0]
        self.save(record)
        for target in targets:multi.add_clip(self.case,target)
        record=self.ready()
        for i in (2,5):
            record['blocks'][i]['speaker_ids']=['S3']
            record['full_draft'][i]['speaker_id']='S3';record['reading_draft'][i]['speaker_id']='S3'
        self.save(record);multi.render(self.case)
        self.assertEqual(multi.audit(self.case)['status'],'PASS')
        self.assertEqual(source.read_text(),text)
        self.assertEqual((self.case/multi.SOURCE).read_text(),text)



    def test_negation_anchor_cannot_be_removed_while_character_ratio_stays_high(self):
        self.make_case();r=self.ready()
        b=next(x for x in r['blocks'] if x['source_label']=='发言人3')
        b['outline']['anchors'].append({'kind':'opposition','quote':'我不同意直接增加投放'})
        for seg in r['reading_draft']:
            if b['id'] in seg['source_ids']:seg['text']=seg['text'].replace('我不同意','我同意')
        self.save(r)
        self.assertTrue(any('关键观点' in x for x in multi.audit(self.case)['errors']))



    def test_confirmed_operations_only_person_is_not_padded_into_the_manuscript(self):
        self.make_case(ops_third=True)
        record=multi.read_json(self.case/multi.RECORD)
        for b in record['blocks']:
            if b['source_label']=='发言人3':multi.add_clip(self.case,b['id'])
        r=self.ready()
        for b in r['blocks']:
            if b['source_label']=='发言人3':
                b['include']=False;b['exclusion']={'category':'operations','reason':'合成原稿中的麦克风确认','confirmed_by':'测试夹具-非真实核对','review_ids':b['review_ids']}
        for key in ('full_draft','reading_draft'):r[key]=[s for s in r[key] if s['speaker_id']!='S3']
        self.save(r);multi.render(self.case)
        self.assertEqual(multi.audit(self.case)['status'],'PASS')
        self.assertNotIn('麦克风',(self.case/multi.MAIN).read_text())
        self.assertIn('麦克风',(self.case/multi.SOURCE).read_text())


if __name__=='__main__':unittest.main()
