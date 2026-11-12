import json
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QEventLoop, QTimer

from prisma.core.toolchain import CommandRunner, DebugSession, Project, artifact_digest


def project_file(tmp_path, script):
    path = tmp_path / 'project.json'
    path.write_text(json.dumps({'version': 1, 'name': 'Teste', 'target': 'HOST',
        'build': [sys.executable, '-c', script], 'artifact': 'firmware.elf',
        'flash': [sys.executable, '-c', 'print("flash-test")', '{artifact}'],
        'debugger': [], 'map_file': 'firmware.map'}))
    return path


@pytest.mark.parametrize('mode', ['ok', 'error', 'timeout'])
def test_execucao_assincrona_build_e_timeout(app, tmp_path, mode):
    script = {'ok': 'from pathlib import Path; Path("firmware.elf").write_bytes(b"ELF-test"); print("build ok")',
              'error': 'import sys; print("main.c:12: error: teste"); sys.exit(2)',
              'timeout': 'import time; time.sleep(20)'}[mode]
    project = Project.load(project_file(tmp_path, script))
    runner = CommandRunner()
    loop = QEventLoop()
    results, output = [], []
    runner.done.connect(lambda ok: (results.append(ok), loop.quit()))
    runner.output.connect(output.append)
    QTimer.singleShot(5000, loop.quit)
    runner.start(project.command('build'), project.directory, timeout_ms=100 if mode == 'timeout' else 3000)
    loop.exec()
    runner.close()
    assert results == [mode == 'ok']
    assert not runner.running
    if mode == 'ok':
        digest = artifact_digest(project.artifact)
        assert len(digest) == 64
        project.artifact.write_bytes(b'changed')
        assert digest != artifact_digest(project.artifact)
        assert project.command('flash')[-1] == str(project.artifact)
    elif mode == 'error':
        assert any('main.c:12: error' in text for text in output)
    else:
        assert any('Tempo limite' in text for text in output)


def test_configuracao_rejeita_shell_implicito_e_executavel_ausente(tmp_path):
    path = project_file(tmp_path, 'pass')
    data = json.loads(path.read_text())
    data['build'] = 'gcc main.c && apagar'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Project.load(path)
    data['build'] = ['executavel_que_nao_existe_prisma']
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Executável não encontrado'):
        Project.load(path).command('build')


def test_gdb_mi_comandos_de_breakpoint_e_registradores(app, tmp_path):
    script = tmp_path / 'fake_gdb.py'
    script.write_text('import sys\nfor line in sys.stdin:\n print(line.strip()+"^done", flush=True)\n')
    path = project_file(tmp_path, 'pass')
    data = json.loads(path.read_text())
    data['debugger'] = [sys.executable, '-u', str(script)]
    path.write_text(json.dumps(data))
    session = DebugSession()
    output = []
    loop = QEventLoop()

    def receive(text):
        output.append(text)
        if 'data-list-register-values x^done' in ''.join(output):
            loop.quit()

    session.output.connect(receive)
    session.start(Project.load(path))
    assert session.process.waitForStarted(3000)
    session.breakpoint('main.c:42')
    session.registers()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    session.close()
    text = ''.join(output)
    assert '-target-select remote localhost:7224' in text
    assert '-break-insert "main.c:42"' in text
    assert '-data-list-register-names' in text
    assert '-data-list-register-values x' in text
    with pytest.raises(ValueError):
        session.breakpoint('main.c:42\n-exec-continue')
