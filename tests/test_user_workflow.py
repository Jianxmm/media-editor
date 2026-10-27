import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from local_support import LocalLock, profile_core, profile_terms
from workspace_tools import render_review
from workspace_tools import stage_time,time_report
from media_intake import fetch


class UserWorkflowTests(unittest.TestCase):
    def test_stage_timing_records_real_interval_without_inventing_human_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch('workspace_tools.time.time',side_effect=[100,105.5]):
                stage_time(root,'start','文字整理')
                result=stage_time(root,'end','文字整理')
            self.assertEqual(result['elapsed_seconds'],5.5)
            with self.assertRaises(ValueError):stage_time(root,'end','文字整理')
            report=time_report(root)
            self.assertEqual(report['human_review'],'未自动计时')
            self.assertIn('5.5',(root/'运行耗时.md').read_text())
    def test_review_groups_same_place_retains_issues_and_checks_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);clip=root/'原声片段.wav';clip.write_bytes(b'synthetic')
            source=root/'issues.json';out=root/'outputs/02.md'
            items={'issues':[{'priority':'P2','location':'00:30','original':'原句','question':'切点检查','clip':clip.name},
                             {'priority':'P1','location':'00:30','original':'原句','question':'金额不确定','draft':'保守写法'},
                             {'priority':'P0','location':'00:05','original':'另一原句','question':'归属冲突'}]}
            source.write_text(json.dumps(items,ensure_ascii=False));before=source.read_bytes()
            r=render_review(source,out);text=out.read_text()
            self.assertEqual((r['issues'],r['locations']),(3,2))
            self.assertLess(text.index('归属冲突'),text.index('金额不确定'))
            self.assertIn('切点检查',text);self.assertIn('保守写法',text);self.assertIn('待核',text)
            self.assertEqual(source.read_bytes(),before)
            clip.unlink()
            with self.assertRaises(ValueError):render_review(source,root/'missing.md')
            out.write_text('human review notes')
            items['issues'][0].pop('clip');source.write_text(json.dumps(items))
            with self.assertRaises(FileExistsError):render_review(source,out)
            self.assertEqual(out.read_text(),'human review notes')

    def test_shared_profile_only_confirms_supported_terms_and_freezes_per_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);profile=root/'profile';case=root/'task';core=profile_core()
            core.init_profile(profile)
            path=profile/'01_专用词库.md'
            path.write_text(path.read_text()+'\n| 云禾 | 产品 | 云合 | — | 已确认 | 用户明确确认的官方名称 |\n| 猜词 | 产品 | — | — | 待确认 | 机器转写 |\n')
            self.assertEqual(profile_terms(profile),['云禾'])
            core.snapshot_profile(case,profile)
            old=(case/'_work/个人资料/01_专用词库.md').read_bytes()
            path.write_text(path.read_text()+'\n新偏好\n')
            with self.assertRaises(FileExistsError):core.snapshot_profile(case,profile)
            self.assertEqual((case/'_work/个人资料/01_专用词库.md').read_bytes(),old)

    def test_advisory_lock_releases_after_abrupt_process_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lock'
            code='import sys,os;sys.path.insert(0,sys.argv[1]);from local_support import LocalLock\nwith LocalLock(sys.argv[2]):os._exit(9)'
            p=subprocess.run([sys.executable,'-c',code,str(ROOT/'scripts'),str(path)])
            self.assertEqual(p.returncode,9)
            with LocalLock(path):
                q=subprocess.run([sys.executable,'-c',code,str(ROOT/'scripts'),str(path)],capture_output=True)
                self.assertNotEqual(q.returncode,9)
            with LocalLock(path):pass

    def test_download_retry_reuses_bound_partial_and_refuses_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);calls=[]
            from subprocess import CompletedProcess
            def fake_run(args):
                calls.append(args)
                if '--dump-single-json' in args:
                    return CompletedProcess(args,0,json.dumps({'id':'one','title':'one'}),'')
                self.assertIn('--continue',args)
                out=Path(args[args.index('-o')+1].replace('%(ext)s','wav'))
                partial=out.with_suffix('.wav.part')
                if not partial.exists():
                    partial.write_bytes(b'first bytes');return CompletedProcess(args,1,'','interrupted')
                out.write_bytes(partial.read_bytes()+b' rest');partial.unlink()
                return CompletedProcess(args,0,'','')
            import media_intake
            with patch.object(media_intake,'required',side_effect=lambda x:x),patch.object(media_intake,'run',side_effect=fake_run),patch.object(media_intake,'probe',return_value=1):
                out=root/'download'
                with self.assertRaisesRegex(ValueError,'同一链接'):fetch('https://example.test/one',out,'audio')
                with self.assertRaises(ValueError):fetch('https://example.test/two',out,'audio')
                result=fetch('https://example.test/one',out,'audio');self.assertFalse(result['reused'])
                n=len(calls);self.assertTrue(fetch('https://example.test/one',out,'audio')['reused'])
                self.assertEqual(len(calls),n)
                self.assertEqual(sum('--dump-single-json' in x for x in calls),1)
                (out/result['media']).write_bytes(b'edited')
                with self.assertRaisesRegex(ValueError,'发生变化'):fetch('https://example.test/one',out,'audio')


if __name__=='__main__':unittest.main()
