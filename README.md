# VoxMorph

**Realtime AI voice changer for Windows.** Speaker-locked preset voices, sub-100 ms latency, a full studio effects rack, and automatic updates.

---

## What makes the preset voices different

Most "voice changers" shift your pitch. Your voice still sounds like *you*, only higher or lower — and everyone can tell.

VoxMorph ships two genuinely different kinds of preset, and the UI labels them clearly:

| | **Identity voices** (RVC) | **Character voices** (DSP) |
|---|---|---|
| What it does | Replaces your timbre with a trained target speaker | Transforms your own timbre |
| Same for every speaker? | **Yes** — you, your sister and your friend all come out as the same person | No — it is relative to each speaker |
| Needs a model file | Yes (~55 MB each) | No |
| Needs a GPU | Strongly recommended | No |
| Latency | 40–150 ms | ~2 ms |

**How identity voices actually work.** RVC splits speech into *content* (what is being said, extracted by a HuBERT encoder that is deliberately speaker-independent) and *identity* (the timbre, which lives entirely in the trained decoder). Your microphone only ever supplies the content and the pitch contour — the decoder always renders it in the target speaker's voice. That is why the output is stable no matter who is at the mic.

## Realism

Two engines, chosen by whether you need realtime:

| | Realtime (phase vocoder) | Offline (WORLD vocoder) |
|---|---|---|
| Used by | Live conversion | `voxmorph morph`, website demos |
| Latency | ~2 ms | ~3 s per 5 s clip |
| Harmonics-to-noise | baseline | **+1.4 to +2.9 dB** on female presets |

A phase vocoder reconstructs each frequency bin's phase independently, which decorrelates the harmonics and produces the hollow "phasiness" that makes a shifted voice sound synthetic. Where latency doesn't matter, VoxMorph instead decomposes speech with WORLD into F0, spectral envelope and aperiodicity, transforms each separately, and resynthesises.

**Gender is not a pitch slider.** Perceptual research converges on three cues, and `dsp/world_morph.py` models all three:

1. **F0** — female/male ratio ≈ 1.5–1.6.
2. **Vocal tract length**, heard as formant positions — female formants sit ~18% higher. Crucially F1 tracks tract length *more weakly* than F2/F3, so the warp is **piecewise, not a single multiplier**; scaling everything uniformly overshoots F1 and produces the classic helium colouration. The curve is also pinned at Nyquist so an upward shift doesn't discard the top octave.
3. **Source spectral tilt** — how fast energy rolls off. This is the cue nearly every voice changer ignores, and it's why they sound like a pitch knob rather than a different person.

Plus aperiodicity scaling for breathiness and smoothed F0 jitter, because perfectly steady pitch is the biggest tell of synthetic speech.

The other things that decide whether a converted voice is believable:

1. **Correct octave.** Auto pitch match measures your natural F0 with a YIN tracker (accurate to under a cent in testing) and shifts it into the target's range.
2. **Clean input.** Denoise → gate → high-pass runs *before* the model. Models hallucinate badly on room tone.
3. **Post-model dynamics.** Compression, de-essing and limiting run *after*, because sibilance and level jumps are the biggest giveaways of AI conversion.

## Speed

Three-thread architecture keeps neural inference off the audio callbacks, so a slow inference block causes a brief buffer dip instead of a hard device dropout.

```
[mic callback]  --> in_ring   (realtime thread, never blocks, never allocates)
[worker thread] --> pre-FX -> voice model -> post-FX --> out_ring
[out callback]  --> drains out_ring to the virtual audio cable
```

The serial DSP loops (gate, limiter, reverb combs) are JIT-compiled with numba — roughly 50–150× faster than interpreted, which is the difference between hitting and missing a 60 ms budget. Measured p95 for the full DSP rack is **~8 ms against a 60 ms block budget**.

Latency profiles: Ultra-Low (~55 ms) · Low (~90 ms) · Balanced (~150 ms) · Max Quality (~250 ms).

## Features

**Voice**
- Identity presets (RVC) — speaker-locked, same output voice for everyone
- 15 built-in character presets — Deep Male, Radio Host, Young Female, Kid, Giant, Demon, Alien, Ghost, Robot, Telephone, Megaphone, Old Man, Chipmunk…
- Zero-shot cloning via Seed-VC — clone a voice from a 5–15 s clip, no training
- Independent pitch (±24 st) and formant (±12 st) control
- Auto pitch matching to the target voice
- Timbre strength, consonant protection, RMS envelope follow
- Selectable pitch engine: rmvpe / fcpe / crepe-tiny / harvest
- Import any `.pth` RVC model by dropping it in the models folder

**Effects rack**
- Spectral denoise with adaptive noise-floor tracking
- Hysteresis noise gate with hold
- Soft-knee compressor with auto make-up
- Split-band de-esser
- 3-band EQ (shelf/peak/shelf)
- Look-ahead brickwall limiter
- Schroeder reverb, echo, 3-voice chorus
- Character colourations: robot, telephone, megaphone, monster, alien, cave, radio
- Autotune

**Workflow**
- Global hotkeys — push-to-talk, mute, bypass, next/previous voice, panic stop
- Soundboard with polyphonic playback, mixed post-conversion
- Dual-track recorder (original + converted, separate files)
- Saveable voice profiles, exportable as `.vmprofile`
- Offline batch file conversion
- Live VU meters, spectrum analyser, latency HUD with realtime-load warning
- System tray, start-with-Windows
- Virtual cable auto-detection with routing guidance
- CLI: `devices`, `voices`, `run`, `convert`, `check-update`, `doctor`

**Updates**
- Checks GitHub Releases on launch and every N hours
- Separate **stable** and **AI-nightly** channels — automated CI builds appear on nightly without disturbing stable users
- Release notes in-app, one-click install, skip-this-version
- **SHA-256 verified** before the installer is ever executed

## Install

Download `VoxMorph-x.y.z-Setup.exe` from [Releases](../../releases) and run it.

You also want a **virtual audio cable** so Discord/OBS/games can hear the converted voice — get [VB-CABLE](https://vb-audio.com/Cable/) (free). The installer reminds you if one is not present.

Then in VoxMorph set **Output → CABLE Input**, and in Discord set **Microphone → CABLE Output**. Use headphones, or your speakers will feed the converted voice back into your mic.

## Run from source

```bash
git clone https://github.com/joeoeiur-cell/voxmorph-voice-changer
cd voxmorph
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt                    # character voices, no GPU needed
python run.py
```

For neural identity voices:

> **Heads up on the RVC ecosystem.** `rvc-python` (last released Oct 2024) pins `numpy<=1.23.5` and `fairseq==0.12.2`, neither of which installs on a current Python. Identity voices therefore need a **dedicated Python 3.10/3.11 environment** — they cannot share the interpreter the packaged app uses. This is exactly why the shipped installer is DSP-only and stays near 180 MB. The engine layer detects a missing backend and falls back cleanly, so nothing breaks either way.

```bash
py -3.10 -m venv .venv-rvc && .venv-rvc\Scripts\activate
pip install "numpy<=1.23.5"
pip install torch==2.1.2+cu118 torchaudio==2.1.2+cu118 --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements-gpu.txt
```

Diagnose any install problem with `python run.py doctor`.

## Build the .exe

```powershell
.\build\build_windows.ps1              # DSP-only build, ~180 MB
.\build\build_windows.ps1 -WithGPU     # bundles torch + RVC, ~2.5 GB
```

Or just push — `.github/workflows/build-release.yml` builds on a Windows runner, compiles the Inno Setup installer, publishes the release and embeds the SHA-256 the updater checks. Tag `v1.2.3` for stable; any push to `main` produces an AI-nightly prerelease.

## Built on

| Project | Role |
|---|---|
| [RVC-Project/Retrieval-based-Voice-Conversion](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) | Identity voice conversion architecture |
| [daswer123/rvc-python](https://github.com/daswer123/rvc-python) | RVC inference as a Python package |
| [deiteris/voice-changer](https://github.com/deiteris/voice-changer) | Realtime chunk+crossfade streaming design (maintained w-okada fork) |
| [Plachtaa/seed-vc](https://github.com/Plachtaa/seed-vc) | Zero-shot voice cloning |
| [IAHispano/Applio](https://github.com/IAHispano/Applio) | RVC training/tooling ecosystem |
| PortAudio · PySide6 · numba · SciPy | Audio I/O, GUI, JIT, DSP |

## Responsible use

Impersonating a real person can be illegal (fraud, defamation, right-of-publicity) and violates the terms of most platforms.

- Only train or use identity voices with the **consent** of the speaker.
- Do not use VoxMorph to deceive, defraud, harass, or bypass voice authentication.
- Some jurisdictions require disclosure of synthetic voices.

No third-party voice checkpoints are bundled or auto-downloaded. You supply your own, and the catalog has a `license` field for recording consent status.

## License

MIT — see [LICENSE](LICENSE). Bundled dependencies keep their own licenses; RVC checkpoints carry the license of whoever trained them.
