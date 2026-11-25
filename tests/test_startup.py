"""Exercise bootstrap contention between independent web/queue processes."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from app import create_app


def test_failed_bootstrap_releases_startup_lock(tmp_path):
    config = dict(DATA_DIR=str(tmp_path / 'data'), ADMIN_EMAIL='admin@example.com',
                  ADMIN_PASSWORD_FILE=str(tmp_path / 'secret'))
    with pytest.raises(FileNotFoundError):
        create_app(config)
    (tmp_path / 'secret').write_text('startup-test-password-123456')
    assert create_app(config).test_client().get('/api/health').status_code == 200


def test_parallel_fresh_start_and_restart(tmp_path):
    secret = tmp_path / 'secret'
    secret.write_text('startup-test-password-123456')
    data = tmp_path / 'data'
    env = dict(os.environ, DATA_DIR=str(data), ADMIN_EMAIL='admin@example.com',
               ADMIN_PASSWORD_FILE=str(secret), BACKUP_DIR=str(tmp_path / 'backups'))
    for generation in range(2):
        gate = tmp_path / ('gate-' + str(generation))
        code = '''
import os,time
from pathlib import Path
from app import create_app
while not Path(os.environ['STARTUP_GATE']).exists():time.sleep(.01)
app=create_app()
assert app.test_client().get('/api/health').status_code==200
'''
        processes = [subprocess.Popen([sys.executable, '-c', code],
                       cwd=Path(__file__).resolve().parents[1],
                       env=dict(env, STARTUP_GATE=str(gate)),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(6)]
        gate.touch()
        try:
            results = [(p, p.communicate(timeout=120)) for p in processes]
            for process, (out, error) in results:
                assert process.returncode == 0, out + error
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        with sqlite3.connect(data / 'passelio.sqlite') as connection:
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 1
