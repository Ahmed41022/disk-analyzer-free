"""Temporarily remove backup access from a permission test's process token."""

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes


class _Luid(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]


class _Privilege(ctypes.Structure):
    _fields_ = [("luid", _Luid), ("attributes", wintypes.DWORD)]


class _TokenPrivileges(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("privileges", _Privilege * 2)]


@contextmanager
def without_backup_privileges() -> Iterator[None]:
    """Disable backup/restore privileges for a scan, restoring their exact prior state."""
    if sys.platform != "win32":
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(_Luid),
    ]
    advapi.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(_TokenPrivileges),
        wintypes.DWORD,
        ctypes.POINTER(_TokenPrivileges),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.AdjustTokenPrivileges.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    token_query_and_adjust = 0x0020 | 0x0008
    if not advapi.OpenProcessToken(
        kernel.GetCurrentProcess(), token_query_and_adjust, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        disabled = _TokenPrivileges()
        disabled.count = 2
        for index, name in enumerate(("SeBackupPrivilege", "SeRestorePrivilege")):
            if not advapi.LookupPrivilegeValueW(
                None, name, ctypes.byref(disabled.privileges[index].luid)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        previous = _TokenPrivileges()
        length = wintypes.DWORD()
        # PreviousState includes exactly the privileges changed, including their enabled bits.
        # https://learn.microsoft.com/windows/win32/api/securitybaseapi/nf-securitybaseapi-adjusttokenprivileges
        if not advapi.AdjustTokenPrivileges(
            token,
            False,
            ctypes.byref(disabled),
            ctypes.sizeof(previous),
            ctypes.byref(previous),
            ctypes.byref(length),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not advapi.AdjustTokenPrivileges(
                token, False, ctypes.byref(previous), 0, None, None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(token)
