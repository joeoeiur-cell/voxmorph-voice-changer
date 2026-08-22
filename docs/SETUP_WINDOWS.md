# Windows setup

## 1. Install VoxMorph

Run `VoxMorph-x.y.z-Setup.exe`. It installs per-user by default, so no admin rights are needed.

## 2. Install a virtual audio cable

**This is the step everyone skips, and it is why "Discord can't hear me".**

VoxMorph produces audio. For another app to *receive* it as a microphone, that audio has to go into a virtual device that presents itself as a recording device.

Install [VB-CABLE](https://vb-audio.com/Cable/) (free). After installing, reboot. You will then have two new devices:

- **CABLE Input** — an *output* device. VoxMorph writes here.
- **CABLE Output** — an *input* device. Other apps listen here.

## 3. Route the audio

```
  Microphone  ──►  VoxMorph  ──►  CABLE Input
                                       │
                                       ▼
                                 CABLE Output  ──►  Discord / OBS / game
```

In VoxMorph → **Audio** tab:
- **Microphone** → your real mic
- **Output** → `CABLE Input`
- Optionally tick **Monitor** and pick your headphones to hear yourself

In Discord: **Settings → Voice & Video → Input Device → `CABLE Output`**.
In OBS: add an **Audio Input Capture** source → `CABLE Output`.

> **Use headphones.** On speakers, your converted voice is picked up by your mic and converted again, which sounds terrible and can feed back.

Turn **off** Discord's noise suppression (Krisp) and echo cancellation — they fight VoxMorph's own processing and muddy the converted voice.

## 4. Pick a voice

Character presets work immediately. Identity voices need a model file — either download one from a catalog you have configured, or drop a `.pth` (plus its `.index` if you have one) into:

```
%LOCALAPPDATA%\VoxMorph\models\
```

Restart VoxMorph, or hit **Refresh** on the Voices panel, and it appears under **My Voices**.

## 5. Tune latency

Start on **Low (~90 ms)**. Watch the **RT Load** figure in the HUD:

| RT Load | Meaning |
|---|---|
| under 50% (green) | Comfortable — try a faster profile |
| 50–80% (amber) | Fine, but no headroom for spikes |
| over 80% (red) | You will get dropouts — use a slower profile |

If you get crackling:
1. Move to a slower latency profile
2. Turn off reverb/echo/chorus
3. Switch pitch engine from `rmvpe` to `fcpe`
4. Enable **WASAPI exclusive mode** (Audio tab)
5. Close other GPU-heavy apps

## Troubleshooting

**"No virtual audio cable detected"** — VB-CABLE is not installed, or you have not rebooted.

**Robotic / warbly output** — usually the wrong octave. Enable **Auto-match pitch**, or set pitch manually (typically −12 for a male speaker on a female model, +12 for the reverse).

**Smeared consonants** — lower **Timbre strength** to ~0.5 and raise **Consonant protect** to ~0.4.

**Hotkeys do nothing** — some anti-cheat drivers block low-level keyboard hooks. Run VoxMorph as administrator, or use the in-app buttons.

**Nothing works and you want details** — run:

```
"C:\Program Files\VoxMorph\VoxMorph-cli.exe" doctor
```

It checks every dependency, lists your devices, reports whether CUDA was found, and tells you exactly what is missing. Logs live in `%LOCALAPPDATA%\VoxMorph\logs\`.
