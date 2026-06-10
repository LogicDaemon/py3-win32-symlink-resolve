""" Resolve Windows symlink targets using the Windows API.
Unlike os.readlink(), this can resolve both absolute and relative symlinks
correctly on Windows, including those that point to UNC paths.
"""
import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import overload

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
# ctypes will assume default signatures (typically c_int return) when
# argtypes/restype are not set. On 64-bit Windows, CreateFileW returning
# a HANDLE without restype = wintypes.HANDLE can truncate the handle value
# and break subsequent DeviceIoControl/CloseHandle calls.
# Thus, argtypes/restype must be defined for CreateFileW, DeviceIoControl,
# and CloseHandle (and optionally GetLastError) before calling them.
kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE)
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.DeviceIoControl.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD),
                                     ctypes.c_void_p)
kernel32.DeviceIoControl.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = (wintypes.HANDLE, )
kernel32.CloseHandle.restype = wintypes.BOOL

FILE_READ_ATTRIBUTES = 0x80
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FSCTL_GET_REPARSE_POINT = 0x000900A8
IO_REPARSE_TAG_SYMLINK = 0xA000000C

# Extended Windows paths (\\?\) can be up to 32,767 characters long.
MAX_EXTENDED_PATH = 32767


class SymbolicLinkReparseBuffer(ctypes.Structure):
    _fields_ = [
        ('SubstituteNameOffset', wintypes.USHORT),
        ('SubstituteNameLength', wintypes.USHORT),
        ('PrintNameOffset', wintypes.USHORT),
        ('PrintNameLength', wintypes.USHORT),
        ('Flags', wintypes.ULONG),
        # PathBuffer could contain two null-terminated strings
        # (SubstituteName and PrintName) back-to-back, so we have to use a byte
        # array to avoid automatic null-termination behavior of ctypes for WCHAR.
        ('PathBuffer', ctypes.c_byte * (MAX_EXTENDED_PATH * 2)),
    ]


class ReparseDataBuffer(ctypes.Structure):
    """ REPARSE_DATA_BUFFER """
    _fields_ = [
        ('ReparseTag', wintypes.ULONG),
        ('ReparseDataLength', wintypes.USHORT),
        ('Reserved', wintypes.USHORT),
        ('SymbolicLinkReparseBuffer', SymbolicLinkReparseBuffer),
    ]


def replace_prefix(text: str, prefix: str, replacement: str) -> str:
    if text.startswith(prefix):
        return replacement + text[len(prefix):]
    return text


def read_handle_symlink_target_win32(handle: wintypes.HANDLE) -> str | None:
    buffer = ReparseDataBuffer()
    bytes_returned = wintypes.DWORD()
    res = kernel32.DeviceIoControl(handle, FSCTL_GET_REPARSE_POINT, None, 0,
                                   ctypes.byref(buffer), ctypes.sizeof(buffer),
                                   ctypes.byref(bytes_returned), None)
    if not res:
        raise ctypes.WinError(ctypes.get_last_error())
    if buffer.ReparseTag != IO_REPARSE_TAG_SYMLINK:
        return None
    sym_buf = buffer.SymbolicLinkReparseBuffer

    # Determine the offset and length in bytes
    offset = sym_buf.PrintNameOffset
    length = sym_buf.PrintNameLength

    # Sometimes PrintName is empty; fallback to SubstituteName
    if length == 0:
        offset = sym_buf.SubstituteNameOffset
        length = sym_buf.SubstituteNameLength

    p_path_buffer = ctypes.addressof(
        sym_buf) + SymbolicLinkReparseBuffer.PathBuffer.offset
    target = ctypes.wstring_at(p_path_buffer + offset, length // 2)

    # When falling back to SubstituteName, Windows commonly returns
    # device-prefixed paths such as \\??\\C:\\...
    # or \\??\\UNC\\server\\share\\....
    # Returning these verbatim will produce a Path that many callers
    # won’t be able to open/compare correctly.
    # Normalizing \\??\\UNC\\ to \\\\ and stripping a leading \\??\\
    # where applicable before returning.
    return replace_prefix(replace_prefix(target, '\\??\\UNC\\', '\\\\'),
                          '\\??\\', '')


@overload
def resolve_symlink(path: Path) -> Path | None:
    ...


@overload
def resolve_symlink(path: str) -> str | None:
    ...


def resolve_symlink(path: Path | str) -> Path | str | None:
    if not (path.is_symlink()
            if isinstance(path, Path) else os.path.islink(path)):
        return None
    # path.readlink() returns an absolute path on Windows,
    # and for relative links it uses the remote root (which is invalid for UNC paths)

    handle = kernel32.CreateFileW(
        str(path) if isinstance(path, Path) else path,
        FILE_READ_ATTRIBUTES,
        7,  # (FILE_SHARE_READ: 1 | FILE_SHARE_WRITE: 2 | FILE_SHARE_DELETE: 4)
        None,
        OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
        None)
    # In standard implementations of Python's ctypes,
    # kernel32.CreateFileW (when its restype is set to
    # wintypes.HANDLE / c_void_p) will automatically unbox the result
    # and return a native Python int (or None if it's a null pointer).
    # handle_val = getattr(handle, 'value', handle)
    # CreateFileW returns INVALID_HANDLE_VALUE on failure.
    # In C, INVALID_HANDLE_VALUE is defined as (HANDLE)-1.
    if handle == -1 or handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        target = read_handle_symlink_target_win32(handle)
    finally:
        kernel32.CloseHandle(handle)
    if isinstance(path, Path) and isinstance(target, str):
        return Path(target)
    return target
