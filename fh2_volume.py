"""Keeps the DualSense speaker endpoint audible for body haptics.

The haptics signal goes through the Windows audio endpoint "Speakers (DualSense
Wireless Controller)", so it follows that endpoint's volume and mute. Other
tools (e.g. a controller app applying a 'speaker volume 0' profile) can mute it,
which silences the haptics while everything else keeps working. This finds the
active DualSense render endpoint(s) and unmutes them / restores the volume.

Plain ctypes COM (IMMDeviceEnumerator -> IMMDevice -> IAudioEndpointVolume);
the calling thread must have COM initialized.
"""
import ctypes
import ctypes.wintypes as W
import uuid
import winreg

_RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
_DEVICE_STATE_ACTIVE = 1
_CLSCTX_ALL = 23


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, text):
        g = cls()
        ctypes.memmove(g.data, uuid.UUID(text).bytes_le, 16)
        return g


CLSID_MMDeviceEnumerator = GUID.of("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID.of("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioEndpointVolume = GUID.of("5CDF2C82-841E-4546-9722-0CF74078229A")

_ole32 = ctypes.WinDLL("ole32")
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, W.DWORD,
                                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
_HRESULT = ctypes.c_long


def _method(ptr, index, restype, *argtypes):
    """Function pointer for vtable slot `index` of COM object `ptr`."""
    vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _release(ptr):
    if ptr:
        _method(ptr, 2, ctypes.c_ulong)(ptr)


def dualsense_endpoint_ids():
    """IDs like '{0.0.0.00000000}.{guid}' of active render endpoints of a DualSense."""
    ids = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _RENDER_KEY)
    except OSError:
        return ids
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            with winreg.OpenKey(root, sub) as k:
                if winreg.QueryValueEx(k, "DeviceState")[0] != _DEVICE_STATE_ACTIVE:
                    continue
            with winreg.OpenKey(root, sub + r"\Properties") as p:
                j, texts = 0, []
                while True:
                    try:
                        _, val, kind = winreg.EnumValue(p, j)
                    except OSError:
                        break
                    j += 1
                    if kind == winreg.REG_SZ:
                        texts.append(val.lower())
            if any("dualsense" in t or "wireless controller" in t for t in texts):
                ids.append("{0.0.0.00000000}." + sub)
        except OSError:
            continue
    return ids


def _endpoint_volume(device_id):
    enum = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
                                 ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum))
    if hr != 0:
        return None
    dev, vol = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        get_device = _method(enum, 5, _HRESULT, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))
        if get_device(enum, device_id, ctypes.byref(dev)) != 0:
            return None
        activate = _method(dev, 3, _HRESULT, ctypes.POINTER(GUID), W.DWORD, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_void_p))
        if activate(dev, ctypes.byref(IID_IAudioEndpointVolume), _CLSCTX_ALL, None, ctypes.byref(vol)) != 0:
            return None
        return vol
    finally:
        _release(dev)
        _release(enum)


def ensure_audible(level=1.0):
    """Unmute the DualSense endpoint(s) and raise the volume to `level` if lower.
    Returns a list of human-readable fixes made (empty if nothing changed)."""
    fixes = []
    for dev_id in dualsense_endpoint_ids():
        vol = _endpoint_volume(dev_id)
        if not vol:
            continue
        try:
            get_mute = _method(vol, 15, _HRESULT, ctypes.POINTER(W.BOOL))
            set_mute = _method(vol, 14, _HRESULT, W.BOOL, ctypes.c_void_p)
            get_level = _method(vol, 9, _HRESULT, ctypes.POINTER(ctypes.c_float))
            set_level = _method(vol, 7, _HRESULT, ctypes.c_float, ctypes.c_void_p)
            muted, cur = W.BOOL(), ctypes.c_float()
            get_mute(vol, ctypes.byref(muted))
            get_level(vol, ctypes.byref(cur))
            if muted.value:
                set_mute(vol, False, None)
                fixes.append("unmuted")
            if cur.value < level - 0.005:
                set_level(vol, ctypes.c_float(level), None)
                fixes.append(f"volume {cur.value * 100:.0f}% -> {level * 100:.0f}%")
        finally:
            _release(vol)
    return fixes


if __name__ == "__main__":
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    print("endpoints:", dualsense_endpoint_ids())
    print("fixes:", ensure_audible() or "none needed")
