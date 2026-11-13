"""Process detection, using the process layout verified on Play Games Beta 26.10.842.1."""
from gpgbridge.procdetect import ProcInfo, classify, is_play_games_path
from gpgbridge.win32 import WindowInfo, game_title, is_game_window

ROOT = r"C:\Program Files\Google\Play Games\current"
SERVICE = ProcInfo(18384, "Service.exe", ROOT + r"\service\Service.exe")
VM_MAIN = ProcInfo(3452, "crosvm.exe", ROOT + r"\emulator\crosvm.exe",
                   (r"..\emulator\crosvm.exe", "run-mp", "--cpus=4", "--cid=3"))
VM_GPU = ProcInfo(19252, "crosvm.exe", ROOT + r"\emulator\crosvm.exe",
                  (ROOT + r"\emulator\crosvm.exe", "device", "gpu", "--bootstrap", "5288"))
GPG_SERVICES = ProcInfo(4660, "GooglePlayGamesServices.exe",
                        r"C:\Program Files\Google\Play Games Services\GooglePlayGamesServices.exe")
OTHER_SERVICE = ProcInfo(4616, "service.exe", r"C:\Program Files\Vendor\service.exe")


def test_nothing_running():
    st = classify([GPG_SERVICES, OTHER_SERVICE])
    assert not st.client_running and not st.emulator_running


def test_client_only_while_emulator_boots():
    st = classify([SERVICE, GPG_SERVICES])
    assert st.client_running and not st.emulator_running
    assert st.client_pids == {18384}


def test_full_session():
    st = classify([SERVICE, VM_MAIN, VM_GPU, GPG_SERVICES, OTHER_SERVICE])
    assert st.client_running and st.emulator_running
    assert st.vm_main_pid == 3452
    assert st.vm_pids == {3452, 19252}
    assert st.all_pids == {18384, 3452, 19252}


def test_device_processes_alone_are_not_the_vm():
    st = classify([SERVICE, VM_GPU])
    assert not st.emulator_running


def test_generic_service_exe_elsewhere_is_ignored():
    assert not classify([OTHER_SERVICE]).client_running


def test_paths_are_case_and_slash_insensitive():
    assert is_play_games_path("c:/program files/google/play games/current/service/service.exe")
    assert not is_play_games_path(r"C:\Program Files\Google\Play Games Services\x.exe")
    assert not is_play_games_path(r"C:\Program Files\Google\Play Games Developer Emulator\crosvm.exe")
    assert not is_play_games_path(None)


def test_open_close_reopen_cycle():
    states = [classify(s) for s in ([], [SERVICE], [SERVICE, VM_MAIN, VM_GPU], [], [SERVICE, VM_MAIN])]
    assert [s.client_running for s in states] == [False, True, True, False, True]
    assert [s.emulator_running for s in states] == [False, False, True, False, True]


# --- game window recognition (verified window layout) ---------------------------

def win(**kw):
    base = dict(hwnd=200350, pid=19252, cls="HwndWrapper[DefaultDomain;;0c74b661]",
                title="Clash of Clans - Player", visible=True, iconic=False, rect=(-7, -7, 1927, 1087))
    base.update(kw)
    return WindowInfo(**base)


def test_visible_game_window_detected():
    assert is_game_window(win())


def test_hidden_offscreen_surface_rejected():
    assert not is_game_window(win(hwnd=200354, title="", visible=False, rect=(-9999, -9999, -9985, -9985)))
    assert not is_game_window(win(rect=(-9999, -9999, -9985, -9985)))


def test_wpf_helper_windows_rejected():
    assert not is_game_window(win(title="Hidden Window"))
    assert not is_game_window(win(cls="CROSVM_1", title="crosvm"))


def test_game_title_strips_gamertag():
    assert game_title("Clash of Clans - Player") == "Clash of Clans"
    assert game_title("Solo") == "Solo"
