"""Minimal read-only access to another process's memory (Windows)."""
import ctypes as C
import ctypes.wintypes as W
import struct
import subprocess

k = C.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def find_pid(name="azimuth.exe"):
    out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                  text=True, creationflags=0x08000000)
    for line in out.splitlines():
        parts = line.strip('"').split('","')
        if parts[0].lower() == name:
            return int(parts[1])
    return None


class Proc:
    def __init__(self, pid):
        self.pid = pid
        self.h = k.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.h:
            raise OSError(C.get_last_error())

    def read(self, addr, n):
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k.ReadProcessMemory(self.h, C.c_void_p(addr), buf, n, C.byref(got)):
            return None
        return buf.raw[:got.value]

    def q(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else None
