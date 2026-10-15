"""Read CurrentDirectory of a foreign same-user process via PEB (read-only diagnostic)."""
import ctypes
import ctypes.wintypes as wt
import sys

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')

PROCESS_QI_VM = 0x0400 | 0x0010 | 0x1000  # QUERY_INFORMATION | VM_READ | QUERY_LIMITED_INFORMATION


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort),
                ("Buffer", ctypes.c_void_p)]


class CURDIR(ctypes.Structure):
    _fields_ = [("DosPath", UNICODE_STRING), ("Handle", ctypes.c_void_p)]


class RTL_USER_PROCESS_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("MaximumLength", ctypes.c_uint32), ("Length", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32), ("DebugFlags", ctypes.c_uint32),
        ("ConsoleHandle", ctypes.c_void_p), ("ConsoleFlags", ctypes.c_uint32),
        ("StandardInput", ctypes.c_void_p), ("StandardOutput", ctypes.c_void_p),
        ("StandardError", ctypes.c_void_p),
        ("CurrentDirectory", CURDIR),
    ]


class PEB(ctypes.Structure):
    _fields_ = [
        ("Inherited", ctypes.c_byte), ("ReadImageFileExecOptions", ctypes.c_byte),
        ("BeingDebugged", ctypes.c_byte), ("BitField", ctypes.c_byte),
        ("Mutant", ctypes.c_void_p), ("ImageBaseAddress", ctypes.c_void_p),
        ("ProcessParameters", ctypes.c_void_p),
    ]


def read_mem(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
        raise OSError(f"ReadProcessMemory@{addr:#x} failed err={ctypes.get_last_error()}")
    return buf.raw[:got.value]


def cwd_of(pid):
    h = k32.OpenProcess(PROCESS_QI_VM, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) failed err={ctypes.get_last_error()}")
    try:
        pbi = ctypes.create_string_buffer(48)
        ret = ctypes.c_ulong()
        if ntdll.NtQueryInformationProcess(h, 0, pbi, 48, ctypes.byref(ret)) != 0:
            raise OSError("NtQueryInformationProcess failed")
        peb_addr = int.from_bytes(pbi.raw[8:16] if ctypes.sizeof(ctypes.c_void_p) == 8 else pbi.raw[4:8], "little")
        peb = PEB.from_buffer_copy(read_mem(h, peb_addr, ctypes.sizeof(PEB)))
        upp = RTL_USER_PROCESS_PARAMETERS.from_buffer_copy(read_mem(h, peb.ProcessParameters, ctypes.sizeof(RTL_USER_PROCESS_PARAMETERS)))
        us = upp.CurrentDirectory.DosPath
        if not us.Length or not us.Buffer:
            return "<unset>"
        raw = read_mem(h, us.Buffer, us.Length)
        return raw.decode("utf-16-le", errors="replace")
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        pid = int(arg)
        try:
            print(f"pid={pid} cwd={cwd_of(pid)}")
        except Exception as exc:
            print(f"pid={pid} ERROR {exc}")
