"""Audio device enumeration and virtual-cable detection.

To be heard in Discord/OBS/games your converted voice must be written to a
*virtual* output device that those apps can select as a microphone. VoxMorph
detects the common ones and tells the user exactly what to pick.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..logging_setup import get_logger

log = get_logger("devices")

VIRTUAL_HINTS = (
    "cable input", "vb-audio", "vb audio", "voicemeeter",
    "virtual audio", "vac ", "blackhole", "soundflower", "pulse: virtual",
)

PREFERRED_HOSTAPIS = ("Windows WASAPI", "Windows WDM-KS", "ASIO", "CoreAudio", "ALSA")


@dataclass
class Device:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_samplerate: float
    is_default_input: bool = False
    is_default_output: bool = False

    @property
    def is_virtual_cable(self) -> bool:
        low = self.name.lower()
        return any(h in low for h in VIRTUAL_HINTS)

    @property
    def label(self) -> str:
        tag = "  [virtual cable]" if self.is_virtual_cable else ""
        return f"{self.name} ({self.hostapi}){tag}"


def _sd():
    try:
        import sounddevice as sd
        return sd
    except Exception as exc:  # pragma: no cover
        log.error("sounddevice unavailable: %s", exc)
        return None


def list_devices() -> List[Device]:
    sd = _sd()
    if sd is None:
        return []
    try:
        raw = sd.query_devices()
        apis = sd.query_hostapis()
        default_in, default_out = sd.default.device
    except Exception as exc:
        log.error("Device enumeration failed: %s", exc)
        return []

    out: List[Device] = []
    for i, d in enumerate(raw):
        out.append(Device(
            index=i,
            name=d.get("name", f"Device {i}"),
            hostapi=apis[d["hostapi"]]["name"] if d.get("hostapi") is not None else "?",
            max_input=d.get("max_input_channels", 0),
            max_output=d.get("max_output_channels", 0),
            default_samplerate=d.get("default_samplerate", 48000.0),
            is_default_input=(i == default_in),
            is_default_output=(i == default_out),
        ))
    return out


def input_devices() -> List[Device]:
    return [d for d in list_devices() if d.max_input > 0]


def output_devices() -> List[Device]:
    return [d for d in list_devices() if d.max_output > 0]


def find_virtual_cable() -> Optional[Device]:
    """Best guess at the virtual cable to route the converted voice into."""
    cands = [d for d in output_devices() if d.is_virtual_cable]
    if not cands:
        return None
    for pref in PREFERRED_HOSTAPIS:
        for d in cands:
            if d.hostapi == pref:
                return d
    return cands[0]


def default_input() -> Optional[Device]:
    for d in input_devices():
        if d.is_default_input:
            return d
    ins = input_devices()
    return ins[0] if ins else None


def default_output() -> Optional[Device]:
    for d in output_devices():
        if d.is_default_output:
            return d
    outs = output_devices()
    return outs[0] if outs else None


def check_supported(device: Optional[int], samplerate: int, channels: int,
                    is_input: bool) -> bool:
    sd = _sd()
    if sd is None:
        return False
    try:
        if is_input:
            sd.check_input_settings(device=device, samplerate=samplerate, channels=channels)
        else:
            sd.check_output_settings(device=device, samplerate=samplerate, channels=channels)
        return True
    except Exception:
        return False


def negotiate_samplerate(in_dev: Optional[int], out_dev: Optional[int],
                         preferred: int = 48000) -> int:
    """Find a sample rate both devices accept."""
    for sr in (preferred, 48000, 44100, 32000, 16000):
        if check_supported(in_dev, sr, 1, True) and check_supported(out_dev, sr, 1, False):
            return sr
    return preferred


def setup_advice() -> List[str]:
    """Human-readable routing guidance shown in the UI."""
    cable = find_virtual_cable()
    tips: List[str] = []
    if cable:
        tips.append(f"Set VoxMorph output to '{cable.name}'.")
        listen = cable.name.replace("Input", "Output")
        tips.append(f"In Discord/OBS/your game, set the microphone to '{listen}'.")
    else:
        tips.append("No virtual audio cable detected.")
        tips.append("Install VB-CABLE (free) so other apps can hear the converted voice.")
        tips.append("Download: https://vb-audio.com/Cable/")
    tips.append("Use headphones - speakers will feed your converted voice back into the mic.")
    return tips
