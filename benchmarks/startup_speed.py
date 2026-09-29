import ctypes
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from benchmarks.source import OUTPUT_DIR

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "VideoCutter"
EXE_NAME = "VideoCutter.exe"
COPY_DIR = OUTPUT_DIR / "startup_copies"
WINDOW_TITLE = "VideoCutter"
TIMEOUT_SEC = 60.0
POLL_SEC = 0.005
RESPONSE_TIMEOUT_MS = 50
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
GENERIC_ALL = 0x10000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STILL_ACTIVE = 259

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


_user32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
_user32.CreateDesktopW.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
_user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, _EnumWindowsProc, wintypes.LPARAM]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
_user32.SendMessageTimeoutW.restype = ctypes.c_size_t
_kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.POINTER(_StartupInfo),
    ctypes.POINTER(_ProcessInformation),
]
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class HiddenDesktop:
    # 程序开在单独的桌面上，窗口不会出现在当前桌面，也拿不走当前应用的键盘焦点
    def __init__(self) -> None:
        self.name = f"VideoCutterBench{uuid.uuid4().hex[:8]}"
        self.handle = _user32.CreateDesktopW(self.name, None, None, 0, GENERIC_ALL, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if not _user32.CloseDesktop(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def main_windows(self) -> list[int]:
        found: list[int] = []

        def visit(hwnd, _param):
            if not _user32.IsWindowVisible(hwnd):
                return True
            title = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, title, 256)
            if title.value == WINDOW_TITLE:
                found.append(hwnd)
            return True

        _user32.EnumDesktopWindows(self.handle, _EnumWindowsProc(visit), 0)
        return found

    def start(self, command: list[str]) -> _ProcessInformation:
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.lpDesktop = self.name
        info = _ProcessInformation()
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        created = _kernel32.CreateProcessW(
            None,
            command_line,
            None,
            None,
            False,
            CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT,
            None,
            str(ROOT),
            ctypes.byref(startup),
            ctypes.byref(info),
        )
        if not created:
            raise ctypes.WinError(ctypes.get_last_error())
        _kernel32.CloseHandle(info.hThread)
        return info


def _responds(hwnd: int) -> bool:
    # 窗口的消息循环处理完这条空消息，说明第一次绘制已经结束，界面可以操作
    result = ctypes.c_size_t()
    return bool(
        _user32.SendMessageTimeoutW(
            hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, RESPONSE_TIMEOUT_MS, ctypes.byref(result)
        )
    )


def _exited(process: _ProcessInformation) -> int | None:
    code = wintypes.DWORD()
    if not _kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code)):
        raise ctypes.WinError(ctypes.get_last_error())
    return None if code.value == STILL_ACTIVE else code.value


def _measure_on(desktop: HiddenDesktop, command: list[str]) -> float:
    # 发送消息的线程要和目标窗口在同一个桌面上
    if not _user32.SetThreadDesktop(desktop.handle):
        raise ctypes.WinError(ctypes.get_last_error())
    start = time.perf_counter()
    process = desktop.start(command)
    try:
        while True:
            windows = desktop.main_windows()
            if windows and _responds(windows[0]):
                return time.perf_counter() - start
            code = _exited(process)
            if code is not None:
                raise RuntimeError(f"process exited with {code} before showing a window")
            if time.perf_counter() - start > TIMEOUT_SEC:
                raise RuntimeError(f"no window after {TIMEOUT_SEC} s")
            time.sleep(POLL_SEC)
    finally:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.dwProcessId)],
            capture_output=True,
            check=False,
        )
        _kernel32.WaitForSingleObject(process.hProcess, 10_000)
        _kernel32.CloseHandle(process.hProcess)


def measure(command: list[str]) -> float:
    desktop = HiddenDesktop()
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["value"] = _measure_on(desktop, command)
        except BaseException as error:
            result["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()
    deadline = time.perf_counter() + 10
    while desktop.main_windows():
        if time.perf_counter() > deadline:
            raise RuntimeError("program window did not close")
        time.sleep(POLL_SEC)
    desktop.close()
    if "error" in result:
        raise result["error"]
    return result["value"]


def fresh_copy(index: int) -> Path:
    # 新复制出的文件还没有被杀毒软件扫描过，用来测量第一次打开的时间
    target = COPY_DIR / f"copy_{index}"
    shutil.copytree(DIST, target)
    return target / EXE_NAME


def first_runs(runs: int) -> list[float]:
    if COPY_DIR.exists():
        shutil.rmtree(COPY_DIR)
    times = [measure([str(fresh_copy(index))]) for index in range(runs)]
    # 程序结束后，杀毒软件可能还在扫描后台加载过的动态库，全部测完再删除
    time.sleep(5)
    shutil.rmtree(COPY_DIR)
    return times


def report(name: str, times: list[float]) -> None:
    text = ", ".join(f"{value:.3f}" for value in times)
    print(f"{name:<14} median {statistics.median(times):.3f} s  min {min(times):.3f} s  runs [{text}]")


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    exe = DIST / EXE_NAME
    if not exe.is_file():
        raise RuntimeError(f"packaged program not found: {exe}")
    report("packaged first", first_runs(runs))
    report("packaged again", [measure([str(exe)]) for _run in range(runs)])
    report("source", [measure([sys.executable, "-m", "videocutter"]) for _run in range(runs)])


if __name__ == "__main__":
    main()
