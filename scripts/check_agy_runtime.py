#!/usr/bin/env python3
"""Check agy's filesystem access without logging in or calling a model."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def check(require_isolation=False, with_codex=False):
    home = Path('/root')
    binary = home / '.local/bin/agy'
    state = home / '.gemini/antigravity-cli'
    cache = home / '.cache/antigravity'
    if not os.access(binary, os.X_OK):
        raise RuntimeError('agy executable is not accessible in this runtime')
    settings = json.loads((state / 'settings.json').read_text())
    # Open and immediately close; never read or print credential contents.
    with (state / 'antigravity-oauth-token').open('rb'):
        pass
    for directory in (state, cache):
        with tempfile.TemporaryFile(dir=directory):
            pass
    if require_isolation:
        hidden = (home / '.ssh', home / '.gemini/oauth_creds.json')
        if not with_codex:
            hidden += (home / '.codex',)
        if any(path.exists() for path in hidden):
            raise RuntimeError('an unrelated home path is visible in this runtime')
        if with_codex and not (home / '.codex/skills/humanizer/SKILL.md').is_file():
            raise RuntimeError('the explicitly configured Codex/humanizer runtime is missing')
    result = subprocess.run([str(binary), '--help'], capture_output=True, text=True, timeout=10)
    if result.returncode != 0 or 'Usage of agy:' not in result.stdout + result.stderr:
        raise RuntimeError('agy --help did not complete successfully')
    return {'success': True, 'executable_accessible': True, 'login_file_readable': True,
            'state_and_cache_writable': True, 'model': settings.get('model'),
            'isolated_home_checked': require_isolation, 'model_called': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-isolation', action='store_true')
    parser.add_argument('--with-codex', action='store_true', help='Expect the optional blog/Codex runtime mapping')
    args = parser.parse_args()
    result = check(args.require_isolation, args.with_codex)
    result_path = os.environ.get('NEWS_CLAW_RESULT_PATH')
    if result_path:
        Path(result_path).write_text(json.dumps(result, ensure_ascii=False) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
