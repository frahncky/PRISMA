"""Comandos de projeto explícitos, sem shell, e verificação do artefato de build."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


@dataclass(frozen=True)
class Project:
    name: str
    target: str
    directory: Path
    build: list[str]
    artifact: Path
    flash: list[str]
    debugger: list[str]
    remote: str
    map_file: Path | None

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Projeto requer version=1")
        for key in ("name", "target", "artifact"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Projeto requer {key}")
        commands = []
        for name in ("build", "flash", "debugger"):
            command = data.get(name, [])
            if not isinstance(command, list) or any(not isinstance(arg, str) or not arg or '\x00' in arg for arg in command):
                raise ValueError(f"{name} deve ser uma lista de argumentos")
            commands.append(command)
        if not commands[0]:
            raise ValueError("Comando de build ausente")
        root = path.resolve().parent
        directory = (root / data.get("directory", ".")).resolve()
        if not directory.is_dir():
            raise ValueError("Diretório do projeto inexistente")
        remote = data.get("remote", "localhost:7224")
        if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+:[0-9]{1,5}", remote):
            raise ValueError("Remote deve ter formato host:porta")
        return cls(data["name"], data["target"], directory, commands[0],
                   (directory / data["artifact"]).resolve(), commands[1], commands[2], remote,
                   (directory / data["map_file"]).resolve() if data.get("map_file") else None)

    def command(self, action: str) -> list[str]:
        command = getattr(self, action)
        if not command:
            raise ValueError(f"Comando {action} não configurado")
        expanded = [arg.replace("{artifact}", str(self.artifact)) for arg in command]
        program = expanded[0]
        if not Path(program).is_absolute() and (self.directory / program).is_file():
            program = str(self.directory / program)
        resolved = shutil.which(program)
        if resolved is None:
            raise ValueError(f"Executável não encontrado: {program}")
        return [resolved, *expanded[1:]]


def artifact_digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("O build não produziu um artefato não vazio")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CommandRunner(QObject):
    output = Signal(str)
    done = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self._active = False
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._active

    def start(self, command: list[str], directory: Path, timeout_ms: int = 120000) -> None:
        if self.running:
            raise ValueError("Uma operação já está em andamento")
        self._active, self._cancelled = True, False
        self.process.setWorkingDirectory(str(directory))
        self.process.start(command[0], command[1:])
        self.timer.start(timeout_ms)

    def _read(self) -> None:
        self.output.emit(bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace"))

    def _finished(self, code: int, status) -> None:
        if self._active:
            self._read()
            self.timer.stop()
            self._active = False
            self.done.emit(not self._cancelled and code == 0 and status == QProcess.ExitStatus.NormalExit)

    def _error(self, error) -> None:
        self.output.emit(self.process.errorString())
        if error == QProcess.ProcessError.FailedToStart and self._active:
            self.timer.stop()
            self._active = False
            self.done.emit(False)

    def _timeout(self) -> None:
        self.output.emit("Tempo limite da operação excedido.")
        self.cancel()

    def cancel(self) -> None:
        self._cancelled = True
        self.process.kill()

    def close(self) -> None:
        if self._active:
            self.cancel()
            self.process.waitForFinished(3000)


class DebugSession(QObject):
    """Cliente GDB/MI para um servidor remoto previamente iniciado pelo usuário."""
    output = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.errorOccurred.connect(lambda _: self.output.emit(self.process.errorString()))
        self.token = 0
        self.pending_remote = ""
        self.process.started.connect(self._connect)

    def start(self, project: Project) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            raise ValueError("Depurador já iniciado")
        command = project.command("debugger")
        self.pending_remote = project.remote
        self.process.setWorkingDirectory(str(project.directory))
        self.process.start(command[0], [*command[1:], "--interpreter=mi2", str(project.artifact)])

    def _connect(self) -> None:
        self.send("-target-select remote " + self.pending_remote)

    def _read(self) -> None:
        self.output.emit(bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace"))

    def send(self, command: str) -> None:
        if self.process.state() != QProcess.ProcessState.Running:
            raise ValueError("Depurador não está em execução")
        self.token += 1
        self.process.write(f"{self.token}{command}\n".encode("utf-8"))

    def breakpoint(self, location: str) -> None:
        if not re.fullmatch(r"[^\r\n\x00]+:[1-9][0-9]*", location):
            raise ValueError("Breakpoint requer arquivo:linha")
        self.send("-break-insert " + json.dumps(location))

    def registers(self) -> None:
        self.send("-data-list-register-names")
        self.send("-data-list-register-values x")

    def close(self) -> None:
        self.process.kill()
        self.process.waitForFinished(3000)
