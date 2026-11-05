"""Run a command with the current Windows user's administrative SID disabled.

This is used by the Windows MFT fallback integration test, which needs to
exercise the same account without its elevated administrator membership.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

if os.name != "nt":
    raise SystemExit("run_restricted.py is available only on Windows")


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
DISABLE_MAX_PRIVILEGE = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
ERROR_NO_TOKEN = 1008


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class STARTUPINFOW(ctypes.Structure):
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
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.GetCurrentThread.restype = wintypes.HANDLE
kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
kernel32.GetStdHandle.restype = wintypes.HANDLE
kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
kernel32.SetHandleInformation.restype = wintypes.BOOL
kernel32.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetHandleInformation.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
kernel32.LocalFree.restype = wintypes.HLOCAL

advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.OpenThreadToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.BOOL,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.OpenThreadToken.restype = wintypes.BOOL
advapi32.ImpersonateSelf.argtypes = [wintypes.DWORD]
advapi32.ImpersonateSelf.restype = wintypes.BOOL
advapi32.RevertToSelf.restype = wintypes.BOOL
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
advapi32.CreateRestrictedToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(SID_AND_ATTRIBUTES),
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.CreateRestrictedToken.restype = wintypes.BOOL
advapi32.CreateProcessAsUserW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
advapi32.CreateProcessAsUserW.restype = wintypes.BOOL


def _raise_last_error(operation: str) -> None:
    raise ctypes.WinError(ctypes.get_last_error(), operation)


def _close_handle(handle: wintypes.HANDLE | None) -> None:
    if handle and handle != wintypes.HANDLE(-1).value:
        kernel32.CloseHandle(handle)


def _get_process_token() -> wintypes.HANDLE:
    token = wintypes.HANDLE()
    current_process = kernel32.GetCurrentProcess()
    if advapi32.OpenProcessToken(
        current_process,
        TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY,
        ctypes.byref(token),
    ):
        return token

    error = ctypes.get_last_error()
    if error != ERROR_NO_TOKEN:
        _raise_last_error("OpenProcessToken")

    # Services can have no process token. ImpersonateSelf supplies the
    # caller's security context, which can then be opened and restricted.
    if not advapi32.ImpersonateSelf(2):  # SecurityImpersonation
        _raise_last_error("ImpersonateSelf")
    try:
        if not advapi32.OpenThreadToken(
            kernel32.GetCurrentThread(),
            TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY,
            True,
            ctypes.byref(token),
        ):
            _raise_last_error("OpenThreadToken")
        return token
    finally:
        advapi32.RevertToSelf()


def _restricted_token(source: wintypes.HANDLE) -> tuple[wintypes.HANDLE, wintypes.HANDLE]:
    sid = wintypes.LPVOID()
    if not advapi32.ConvertStringSidToSidW("S-1-5-32-544", ctypes.byref(sid)):
        _raise_last_error("ConvertStringSidToSidW")
    entry = SID_AND_ATTRIBUTES(sid, 0)
    restricted = wintypes.HANDLE()
    try:
        if not advapi32.CreateRestrictedToken(
            source,
            DISABLE_MAX_PRIVILEGE,
            1,
            ctypes.byref(entry),
            0,
            None,
            0,
            None,
            ctypes.byref(restricted),
        ):
            _raise_last_error("CreateRestrictedToken")
    except BaseException:
        kernel32.LocalFree(sid)
        raise
    return restricted, sid


def run(argv: list[str]) -> int:
    if not argv:
        print("usage: run_restricted.py COMMAND [ARG ...]", file=sys.stderr)
        return 2

    source_token = restricted_token = sid = None
    process_info = PROCESS_INFORMATION()
    inherit_handles: list[tuple[wintypes.HANDLE, bool]] = []
    try:
        source_token = _get_process_token()
        restricted_token, sid = _restricted_token(source_token)

        std_handles = []
        for standard_id in (STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            handle = kernel32.GetStdHandle(standard_id)
            if not handle or handle == wintypes.HANDLE(-1).value:
                _raise_last_error("GetStdHandle")
            original_flags = wintypes.DWORD()
            if not kernel32.GetHandleInformation(handle, ctypes.byref(original_flags)):
                _raise_last_error("GetHandleInformation")
            was_inheritable = bool(original_flags.value & HANDLE_FLAG_INHERIT)
            if not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
                _raise_last_error("SetHandleInformation")
            std_handles.append(handle)
            inherit_handles.append((handle, was_inheritable))

        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = STARTF_USESTDHANDLES
        startup.hStdInput, startup.hStdOutput, startup.hStdError = std_handles

        # list2cmdline implements the Windows CRT quoting rules and preserves
        # argv values containing spaces, quotes, and trailing backslashes.
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        if not advapi32.CreateProcessAsUserW(
            restricted_token,
            None,
            command_line,
            None,
            None,
            True,
            0,
            None,
            None,
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            _raise_last_error("CreateProcessAsUserW")

        kernel32.WaitForSingleObject(process_info.hProcess, 0xFFFFFFFF)
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            _raise_last_error("GetExitCodeProcess")
        return int(exit_code.value)
    finally:
        _close_handle(process_info.hThread)
        _close_handle(process_info.hProcess)
        for handle, was_inheritable in reversed(inherit_handles):
            kernel32.SetHandleInformation(
                handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT if was_inheritable else 0
            )
        _close_handle(restricted_token)
        _close_handle(source_token)
        if sid:
            kernel32.LocalFree(sid)


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    try:
        raise SystemExit(run(arguments))
    except OSError as exc:
        print(f"run_restricted.py: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
