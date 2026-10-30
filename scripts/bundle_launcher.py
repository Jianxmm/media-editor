"""Dispatch the portable launchers using only the package's own runtime."""
from pathlib import Path
import runpy
import sys

from bundled_runtime import prepare_environment

ROOT=Path(__file__).resolve().parents[1]


def main():
    prepare_environment()
    args=sys.argv[1:]
    mode=args[0] if args else ''
    routes={'install':ROOT/'install.py',
            'core':ROOT/'.livestream-core/scripts/livestream.py',
            'multi':ROOT/'scripts/multi_livestream.py',
            'workspace':ROOT/'scripts/workspace_tools.py'}
    script=routes.get(mode,ROOT/'scripts/media_intake.py')
    sys.argv=[str(script),*(args[1:] if mode in routes else args)]
    runpy.run_path(str(script),run_name='__main__')


if __name__=='__main__':main()
