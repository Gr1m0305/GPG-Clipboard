"""Detect whether Google Play Games (PC) and its emulator are running.

Verified on Play Games Beta 26.10.842.1 (see PROGRESS.md, Part 1 section 5):
  client   : Service.exe  in  ...\\Google\\Play Games\\current\\service\\
  VM main  : crosvm.exe   in  ...\\Google\\Play Games\\current\\emulator\\  with 'run-mp' argument
  NOT open : GooglePlayGamesServices.exe in ...\\Google\\Play Games Services\\ (always-on Windows service)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

CLIENT_EXE = "service.exe"
VM_EXE = "crosvm.exe"
VM_MAIN_ARG = "run-mp"


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    exe: str = ""
    cmdline: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpgState:
    client_pids: frozenset[int] = field(default_factory=frozenset)
    vm_pids: frozenset[int] = field(default_factory=frozenset)  # every crosvm.exe of Play Games
    vm_main_pid: int | None = None

    @property
    def client_running(self) -> bool:
        return bool(self.client_pids)

    @property
    def emulator_running(self) -> bool:
        return self.vm_main_pid is not None

    @property
    def all_pids(self) -> frozenset[int]:
        return self.client_pids | self.vm_pids


def is_play_games_path(exe: str | None) -> bool:
    """True for files inside the Play Games install (not 'Play Games Services' or the Developer Emulator)."""
    if not exe:
        return False
    p = exe.replace("/", "\\").lower()
    return "\\google\\play games\\" in p


def classify(procs: Iterable[ProcInfo]) -> GpgState:
    client, vms = set(), set()
    vm_main = None
    for p in procs:
        name = p.name.lower()
        if not is_play_games_path(p.exe):
            continue
        if name == CLIENT_EXE:
            client.add(p.pid)
        elif name == VM_EXE:
            vms.add(p.pid)
            if VM_MAIN_ARG in (a.lower() for a in p.cmdline):
                vm_main = p.pid
    return GpgState(frozenset(client), frozenset(vms), vm_main)


def scan() -> GpgState:
    """Cheap psutil scan: names for every process, exe/cmdline only for the two candidates."""
    import psutil

    procs: list[ProcInfo] = []
    for p in psutil.process_iter(["pid", "name"]):
        name = (p.info.get("name") or "").lower()
        if name not in (CLIENT_EXE, VM_EXE):
            continue
        try:
            exe = p.exe()
            cmd = tuple(p.cmdline()) if name == VM_EXE else ()
        except (psutil.Error, OSError):
            continue
        procs.append(ProcInfo(p.info["pid"], name, exe, cmd))
    return classify(procs)


def vm_boot_flags(vm_main_pid: int | None) -> dict[str, str]:
    """androidboot.* flags from the VM command line (used by `diagnose`)."""
    if vm_main_pid is None:
        return {}
    import psutil

    try:
        cmd = " ".join(psutil.Process(vm_main_pid).cmdline())
    except (psutil.Error, OSError):
        return {}
    flags = {}
    for tok in cmd.replace('"', " ").split():
        if tok.startswith("androidboot.") and "=" in tok:
            k, v = tok.split("=", 1)
            flags[k] = v
    return flags
