import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'git and bash required')
class PersistenceIntegration(unittest.TestCase):
    def test_isolated_state_branch_and_idempotent_push(self):
        script = Path(__file__).resolve().parent.parent / 'persist.sh'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote, source, runner = root / 'remote.git', root / 'source', root / 'runner'
            def git(*args, cwd=None):
                return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
            git('init', '--bare', str(remote))
            git('clone', str(remote), str(source))
            git('config', 'user.name', 'Fixture', cwd=source)
            git('config', 'user.email', 'fixture@example.invalid', cwd=source)
            (source / 'README.md').write_text('Preserve this source')
            git('add', '.', cwd=source)
            git('commit', '-m', 'fixture source', cwd=source)
            git('push', 'origin', 'HEAD:main', cwd=source)
            main = git('rev-parse', 'HEAD', cwd=source)
            checkpoint = runner / 'growth-checkpoint'
            (checkpoint / 'reports').mkdir(parents=True)
            (checkpoint / 'state.sqlite3').write_bytes(b'fixture state')
            (checkpoint / 'state.sqlite3.lock').write_text('do not publish')
            (checkpoint / 'reports' / 'report.json').write_text(json.dumps({'fixture': True}))
            env = {**os.environ, 'RUNNER_TEMP': str(runner)}
            def persist():
                subprocess.run(['bash', str(script)], cwd=source, env=env, capture_output=True, check=True)
            persist()
            first = git('--git-dir=' + str(remote), 'rev-parse', 'growth-data')
            files = git('--git-dir=' + str(remote), 'ls-tree', '-r', '--name-only', 'growth-data')
            self.assertEqual(set(files.splitlines()), {'state.sqlite3', 'reports/report.json'})
            self.assertEqual(git('--git-dir=' + str(remote), 'rev-parse', 'main'), main)
            # Each workflow has a fresh runner path. Same contents must not create a commit.
            git('worktree', 'remove', '--force', str(runner / 'growth-data'), cwd=source)
            persist()
            self.assertEqual(git('--git-dir=' + str(remote), 'rev-parse', 'growth-data'), first)
            git('worktree', 'remove', '--force', str(runner / 'growth-data'), cwd=source)
            (checkpoint / 'state.sqlite3').write_bytes(b'updated fixture state')
            persist()
            self.assertNotEqual(git('--git-dir=' + str(remote), 'rev-parse', 'growth-data'), first)
            self.assertEqual(git('--git-dir=' + str(remote), 'rev-parse', 'main'), main)
