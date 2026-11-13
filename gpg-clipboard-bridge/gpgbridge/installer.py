r"""Per-user install / uninstall of the packaged build. No admin rights needed.

GPGClipboardBridge-Setup.exe calls setup_main(). The installed "GPGClipboardBridge.exe uninstall"
(which Settings > Apps runs) calls uninstall_main(). Everything is for the current user only:

  %LOCALAPPDATA%\Programs\GPG Clipboard Bridge\   the program (GPGClipboardBridge.exe + _internal\)
  Scheduled Task "GPG Clipboard Bridge"           starts it at logon and re-checks every 5 minutes; if this PC
                                                  only lets admins create logon tasks, an HKCU ...\Run value
                                                  starts it at logon instead
  Start menu shortcut "GPG Clipboard Bridge"      starts it again after tray > Quit
  HKCU ...\Uninstall\gpg-clipboard-bridge         the Settings > Apps entry

Exports in Documents\GPG Clipboard Exports are never deleted.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from . import APP_ID, APP_NAME, __version__
from .config import FOLDERID_PROGRAMS, FOLDERID_USER_PROGRAM_FILES, data_dir, known_folder
from .runtime import EXE_NAME, app_root, frozen, self_command

log = logging.getLogger("installer")

TASK_NAME = APP_NAME
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = APP_NAME
UNINSTALL_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_ID
PUBLISHER = "Gr1m0305"
PROJECT_URL = "https://github.com/Gr1m0305/GPG-Clipboard"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = 0x00000008

MB_YESNO, MB_ICONERROR, MB_ICONQUESTION, MB_ICONWARNING, MB_ICONINFORMATION = 0x4, 0x10, 0x20, 0x30, 0x40
MB_SETFOREGROUND = 0x10000
IDYES = 6
ERROR_CANCELLED = 1602  # what installers return when the user says No


class InstallError(RuntimeError):
    pass


# -- small helpers ---------------------------------------------------------------------------------

def message_box(text: str, flags: int = MB_ICONINFORMATION, title: str = APP_NAME) -> int:
    try:
        return ctypes.WinDLL("user32").MessageBoxW(None, text, title, flags | MB_SETFOREGROUND)
    except (OSError, AttributeError):
        return 0


def default_install_dir() -> Path:
    base = known_folder(FOLDERID_USER_PROGRAM_FILES)
    if not base:
        base = os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"), "Programs")
    return Path(base) / APP_NAME


def start_menu_shortcut() -> Path:
    base = known_folder(FOLDERID_PROGRAMS)
    if not base:
        base = os.path.join(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"),
                            r"Microsoft\Windows\Start Menu\Programs")
    return Path(base) / f"{APP_NAME}.lnk"


def current_user() -> str:
    r"""DOMAIN\user of this account, the form Task Scheduler expects."""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = ctypes.c_ulong(len(buf))
        if ctypes.WinDLL("secur32").GetUserNameExW(2, buf, ctypes.byref(size)):  # NameSamCompatible
            return buf.value
    except (OSError, AttributeError):
        pass
    dom, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME", "")
    return f"{dom}\\{user}" if dom else user


def _run(cmd: list[str], timeout: float = 60, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, **kw)


def _looks_like_install(folder: Path | None) -> bool:
    return bool(folder) and (Path(folder) / EXE_NAME).is_file()


def dir_size_kb(folder: Path) -> int:
    total = 0
    for p in Path(folder).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total // 1024


@dataclass(frozen=True)
class StartCommand:
    program: str
    arguments: str
    workdir: str

    @property
    def command_line(self) -> str:
        return f'"{self.program}" {self.arguments}'.strip()


def installed_command(install_dir: Path) -> StartCommand:
    return StartCommand(str(Path(install_dir) / EXE_NAME), "supervisor", str(install_dir))


def current_command() -> StartCommand:
    """How this copy of the helper (packaged or source checkout) is started at logon."""
    if frozen():
        return installed_command(app_root())
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = self_command("supervisor")
    return StartCommand(str(pyw if pyw.exists() else exe), subprocess.list2cmdline(cmd[1:]), str(app_root()))


# -- Scheduled Task / Run key -------------------------------------------------------------------------

def task_xml(cmd: StartCommand, user: str, logon_trigger: bool = True, today: dt.date | None = None) -> str:
    """Task definition: at logon (optional) + every 5 minutes, hidden, no time limit, one instance."""
    start = f"{(today or dt.date.today()).isoformat()}T00:00:00"
    logon = (f"""
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>""" if logon_trigger else "")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Copies Google Play Games (PC) clipboard exports to the Windows clipboard. Installed by {escape(APP_NAME)} {escape(__version__)}.</Description>
    <URI>\\{escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>{logon}
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(cmd.program)}</Command>
      <Arguments>{escape(cmd.arguments)}</Arguments>
      <WorkingDirectory>{escape(cmd.workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def register_task(cmd: StartCommand, logon_trigger: bool = True) -> bool:
    fd, tmp = tempfile.mkstemp(prefix="gpgbridge-task-", suffix=".xml")
    os.close(fd)
    try:
        Path(tmp).write_text(task_xml(cmd, current_user(), logon_trigger), encoding="utf-16")
        r = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", tmp, "/F"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("could not run schtasks: %s", exc)
        return False
    finally:
        Path(tmp).unlink(missing_ok=True)
    if r.returncode != 0:
        log.warning("schtasks /Create (logon trigger=%s) failed: %s", logon_trigger, (r.stderr or r.stdout).strip())
        return False
    log.info("registered Scheduled Task '%s' (logon trigger=%s)", TASK_NAME, logon_trigger)
    return True


def task_exists() -> bool:
    try:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME], timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def task_enabled() -> bool:
    """Registered and not disabled."""
    try:
        r = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        return False
    xml = r.stdout
    settings = xml[xml.find("<Settings>"):xml.find("</Settings>")]
    return "<Enabled>false</Enabled>" not in settings


def end_task() -> None:
    try:
        _run(["schtasks", "/End", "/TN", TASK_NAME], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


def delete_task() -> None:
    try:
        r = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], timeout=20)
        if r.returncode == 0:
            log.info("removed Scheduled Task '%s'", TASK_NAME)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_task() -> bool:
    try:
        return _run(["schtasks", "/Run", "/TN", TASK_NAME], timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_run_value() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_VALUE)[0]
    except OSError:
        return None


def set_run_value(cmd: StartCommand) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmd.command_line)
    log.info("start at logon via HKCU Run: %s", cmd.command_line)


def delete_run_value() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except OSError:
        pass


def register_startup(cmd: StartCommand) -> str:
    """Make the helper start at every logon. Returns 'task', 'run-key+task' or 'run-key'."""
    if register_task(cmd, logon_trigger=True):
        delete_run_value()
        return "task"
    # Some PCs only let admins create logon-triggered tasks. Start at logon from the Run key instead and keep
    # the 5-minute task (if allowed) as crash recovery.
    set_run_value(cmd)
    return "run-key+task" if register_task(cmd, logon_trigger=False) else "run-key"


def startup_enabled() -> bool:
    return get_run_value() is not None or task_enabled()


def set_startup_enabled(enabled: bool, cmd: StartCommand | None = None) -> None:
    """Tray > Start with Windows."""
    if enabled:
        if task_exists():
            _run(["schtasks", "/Change", "/TN", TASK_NAME, "/ENABLE"], timeout=20)
            if not task_enabled():
                register_startup(cmd or current_command())
        else:
            register_startup(cmd or current_command())
    else:
        delete_run_value()
        if task_exists():
            _run(["schtasks", "/Change", "/TN", TASK_NAME, "/DISABLE"], timeout=20)
    log.info("start with Windows: %s", "on" if enabled else "off")


# -- shortcut / Apps & features entry ------------------------------------------------------------------

def create_shortcut(lnk: Path, target: Path, arguments: str = "", description: str = "") -> None:
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:GPGB_LNK); "
              "$s.TargetPath = $env:GPGB_TARGET; $s.Arguments = $env:GPGB_ARGS; "
              "$s.WorkingDirectory = $env:GPGB_DIR; $s.IconLocation = $env:GPGB_TARGET + ',0'; "
              "$s.Description = $env:GPGB_DESC; $s.Save()")
    env = dict(os.environ, GPGB_LNK=str(lnk), GPGB_TARGET=str(target), GPGB_ARGS=arguments,
               GPGB_DIR=str(Path(target).parent), GPGB_DESC=description)
    lnk.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
             env=env)
    if r.returncode != 0 or not lnk.exists():
        raise InstallError(f"could not create {lnk}: {(r.stderr or r.stdout).strip()}")
    log.info("created shortcut %s", lnk)


def uninstall_values(install_dir: Path, size_kb: int, today: dt.date | None = None) -> dict:
    exe = Path(install_dir) / EXE_NAME
    return {
        "DisplayName": APP_NAME,
        "DisplayVersion": __version__,
        "Publisher": PUBLISHER,
        "DisplayIcon": f"{exe},0",
        "InstallLocation": str(install_dir),
        "UninstallString": f'"{exe}" uninstall',
        "QuietUninstallString": f'"{exe}" uninstall --quiet',
        "URLInfoAbout": PROJECT_URL,
        "HelpLink": PROJECT_URL,
        "InstallDate": (today or dt.date.today()).strftime("%Y%m%d"),
        "NoModify": 1,
        "NoRepair": 1,
        "EstimatedSize": int(size_kb),
    }


def write_uninstall_entry(install_dir: Path, size_kb: int) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE) as k:
        for name, value in uninstall_values(install_dir, size_kb).items():
            if isinstance(value, int):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    log.info("wrote Apps & features entry HKCU\\%s", UNINSTALL_KEY)


def delete_uninstall_entry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def existing_install() -> tuple[Path | None, str | None]:
    """(InstallLocation, DisplayVersion) from the Apps & features entry, if installed."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            def get(name):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return None
            loc, ver = get("InstallLocation"), get("DisplayVersion")
            return (Path(loc) if loc else None), ver
    except OSError:
        return None, None


# -- processes / files ------------------------------------------------------------------------------------

def find_running(exclude: set[int] | None = None) -> list:
    """Running helper processes: the packaged exe, or python(w) running `-m gpgbridge supervisor|bridge`."""
    import psutil

    exclude = exclude or set()
    found = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        if p.info["pid"] in exclude:
            continue
        name = (p.info.get("name") or "").lower()
        if name == EXE_NAME.lower():
            found.append(p)
        elif name in ("python.exe", "pythonw.exe"):
            cmd = " ".join(p.info.get("cmdline") or [])
            if "-m gpgbridge" in cmd and (" supervisor" in cmd or " bridge" in cmd):
                found.append(p)
    return found


def stop_running() -> int:
    """Stop every running copy of the helper (other than this process). Returns how many were stopped."""
    import psutil

    end_task()
    procs = find_running({os.getpid()})
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=8)
    if procs:
        log.info("stopped %d running helper process(es)", len(procs))
    return len(procs)


def _rmtree_retry(folder: Path, attempts: int = 20) -> None:
    for i in range(attempts):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(0.5)  # files of a process that is still exiting


def copy_program(src: Path, dst: Path) -> None:
    if dst.exists() and any(dst.iterdir()) and not _looks_like_install(dst):
        raise InstallError(f"{dst} already exists and is not a {APP_NAME} folder. Choose another folder.")
    if dst.exists():
        _rmtree_retry(dst)
    shutil.copytree(src, dst)
    log.info("copied program files to %s", dst)


QUIT_MARKER_NAME = "quit.marker"


def clear_quit_marker() -> None:
    (data_dir() / QUIT_MARKER_NAME).unlink(missing_ok=True)


def wait_until_running(timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any("supervisor" in " ".join(p.info.get("cmdline") or []) for p in find_running({os.getpid()})):
            return True
        time.sleep(0.5)
    return False


def start_now(cmd: StartCommand, startup: str) -> bool:
    clear_quit_marker()
    if startup in ("task", "run-key+task") and run_task() and wait_until_running():
        return True
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (CREATE_BREAKAWAY_FROM_JOB, 0):
        try:
            subprocess.Popen([cmd.program, *cmd.arguments.split()], cwd=cmd.workdir, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags | extra)
            break
        except OSError as exc:
            log.warning("start failed (flags %#x): %s", flags | extra, exc)
    return wait_until_running()


def remove_settings() -> None:
    """Logs, config.json and markers. Never the exports; leaves a source checkout's venv alone."""
    d = data_dir()
    for name in ("config.json", QUIT_MARKER_NAME, "health-check.txt"):
        (d / name).unlink(missing_ok=True)
    shutil.rmtree(d / "logs", ignore_errors=True)
    try:
        d.rmdir()  # only if now empty
    except OSError:
        pass


def schedule_removal(folder: Path) -> None:
    """Delete the program folder after this process exits (a running exe cannot delete itself)."""
    f = str(folder).rstrip("\\")
    script = (f'for /l %i in (1,1,40) do (rmdir /s /q "{f}" 2>nul & if not exist "{f}\\" exit /b 0 '
              f'& ping -n 2 127.0.0.1 >nul)')
    for extra in (CREATE_BREAKAWAY_FROM_JOB, 0):
        try:
            subprocess.Popen(f"cmd.exe /d /c {script}", cwd=tempfile.gettempdir(), close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | extra)
            log.info("scheduled removal of %s", f)
            return
        except OSError as exc:
            log.warning("could not schedule removal (flags %#x): %s", extra, exc)


# -- install / uninstall -------------------------------------------------------------------------------------

@dataclass
class InstallResult:
    install_dir: Path
    startup: str
    shortcut: bool
    started: bool
    previous_version: str | None


def install(payload: Path, target: Path | None = None, start: bool = True) -> InstallResult:
    payload = Path(payload)
    if not _looks_like_install(payload):
        raise InstallError(f"the program files are missing from the installer ({payload})")
    prev_dir, prev_ver = existing_install()
    target = Path(target) if target else (prev_dir if _looks_like_install(prev_dir) else default_install_dir())
    log.info("installing %s %s to %s (previous: %s)", APP_NAME, __version__, target, prev_ver or "none")
    stop_running()
    copy_program(payload, target)
    cmd = installed_command(target)
    startup = register_startup(cmd)
    shortcut = True
    try:
        create_shortcut(start_menu_shortcut(), target / EXE_NAME,
                        description="Google Play Games clipboard helper (starts it if you chose Quit)")
    except Exception as exc:  # not fatal: it still starts at logon
        shortcut = False
        log.warning("%s", exc)
    write_uninstall_entry(target, dir_size_kb(target))
    started = start_now(cmd, startup) if start else False
    log.info("install finished: startup=%s shortcut=%s started=%s", startup, shortcut, started)
    return InstallResult(target, startup, shortcut, started, prev_ver)


def uninstall(program_dir: Path | None = None, keep_settings: bool = False) -> Path | None:
    """Undo install(). Returns the program folder still to delete (see schedule_removal), if any."""
    if program_dir is None:
        program_dir = app_root() if frozen() else existing_install()[0]
    log.info("uninstalling %s (program folder %s)", APP_NAME, program_dir)
    stop_running()
    delete_task()
    delete_run_value()
    start_menu_shortcut().unlink(missing_ok=True)
    delete_uninstall_entry()
    if keep_settings:
        clear_quit_marker()
    else:
        remove_settings()
    return Path(program_dir) if _looks_like_install(program_dir) else None


# -- entry points (GUI, no console) ---------------------------------------------------------------------------

def _log_to(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)


def _exports_dir() -> str:
    try:
        from .config import load
        return load(write_default=False)["exports_dir"]
    except Exception:
        return r"Documents\GPG Clipboard Exports"


def setup_main(argv: list[str], payload: Path) -> int:
    """GPGClipboardBridge-Setup.exe [/S | --silent] [--no-start] [--dir PATH]"""
    flags = {a.lower() for a in argv}
    silent = bool(flags & {"/s", "/silent", "/verysilent", "--silent", "-s", "/q", "--quiet"})
    start = "--no-start" not in flags
    target = None
    if "--dir" in flags:
        i = [a.lower() for a in argv].index("--dir")
        if i + 1 < len(argv):
            target = Path(argv[i + 1])
    log_path = data_dir() / "logs" / "install.log"
    _log_to(log_path)

    prev_dir, prev_ver = existing_install()
    where = target or (prev_dir if _looks_like_install(prev_dir) else default_install_dir())
    if not silent:
        if prev_ver == __version__:
            head = f"Reinstall {APP_NAME} {__version__}?"
        elif prev_ver:
            head = f"Update {APP_NAME} from {prev_ver} to {__version__}?"
        else:
            head = f"Install {APP_NAME} {__version__}?"
        text = (f"{head}\n\n"
                "It sits in the system tray, starts by itself when you sign in to Windows, and puts text you "
                "copy inside Google Play Games (for example Clash of Clans > Data Export > Copy to clipboard) "
                "on the Windows clipboard so you can paste it in Discord.\n\n"
                f"Installs for your account only (no admin rights needed) to:\n{where}")
        if message_box(text, MB_YESNO | MB_ICONQUESTION) != IDYES:
            log.info("setup cancelled")
            return ERROR_CANCELLED
    try:
        res = install(payload, target, start=start)
    except Exception as exc:
        log.exception("setup failed")
        if not silent:
            message_box(f"Setup failed: {exc}\n\nDetails: {log_path}", MB_ICONERROR)
        return 1
    if not silent:
        lines = [f"{APP_NAME} {__version__} is installed" + (" and running." if res.started else ".")]
        if start and not res.started:
            lines.append(f"\nIt did not start by itself. Open \"{APP_NAME}\" from the Start menu. Details: {log_path}")
        lines += [
            "",
            "- Look for the clipboard icon in the system tray (click ^ next to the clock if you can't see it).",
            "- It starts automatically every time you sign in. You never need to open it.",
            "- In the game press Copy to clipboard, wait for the \"Copied ... characters\" notification, then "
            "paste in Discord.",
            f"- Every export is also saved in {_exports_dir()}",
            "",
            f"To remove it: Settings > Apps > {APP_NAME} > Uninstall.",
        ]
        message_box("\n".join(lines), MB_ICONINFORMATION if (res.started or not start) else MB_ICONWARNING)
    return 0


def uninstall_main(quiet: bool = False) -> int:
    _log_to(Path(tempfile.gettempdir()) / f"{APP_ID}-uninstall.log")
    if not quiet and message_box(
            f"Remove {APP_NAME} from this PC?\n\nYour saved exports in {_exports_dir()} are kept.",
            MB_YESNO | MB_ICONQUESTION) != IDYES:
        return ERROR_CANCELLED
    try:
        folder = uninstall()
    except Exception as exc:
        log.exception("uninstall failed")
        if not quiet:
            message_box(f"Uninstall failed: {exc}", MB_ICONERROR)
        return 1
    if not quiet:
        message_box(f"{APP_NAME} was removed.", MB_ICONINFORMATION)
    if folder is not None:
        schedule_removal(folder)
    return 0
