"""End-to-end checks that run without any audio hardware."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voxmorph.audio.ringbuffer import RingBuffer
from voxmorph.config import Config, FXConfig
from voxmorph.dsp.chain import FXChain
from voxmorph.engines.base import StreamingContext
from voxmorph.engines.dsp_engine import DSPEngine
from voxmorph.presets.manager import Preset, PresetManager
from voxmorph.presets.profiles import ProfileStore, VoiceProfile
from voxmorph.soundboard import Soundboard

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")


# ----------------------------------------------------------------- ringbuffer
print("\nRing buffer")
rb = RingBuffer(1000)
rb.write(np.arange(500, dtype=np.float32))
got = rb.read(500)
check("write/read round trip", np.allclose(got, np.arange(500)))
rb.clear()
rb.write(np.ones(1500, dtype=np.float32))
check("overflow drops oldest, never grows", len(rb) == 1000 and rb.overflows == 1)
rb.clear()
rb.write(np.ones(10, dtype=np.float32))
out = rb.read(100)
check("underflow zero-fills instead of blocking",
      len(out) == 100 and out[10:].sum() == 0 and rb.underflows == 1)

# --------------------------------------------------------- streaming context
print("\nStreaming context (crossfade continuity)")
ctx = StreamingContext(16000, context_ms=500, crossfade_ms=20)
blk = 512
sig = np.sin(2 * np.pi * 220 * np.arange(16000) / 16000).astype(np.float32)
emitted = []
for i in range(0, len(sig) - blk, blk):
    fed = ctx.build_input(sig[i:i + blk])
    emitted.append(ctx.extract_output(fed, blk))   # identity "model"
out = np.concatenate(emitted)
check("output length matches input", len(out) == len(emitted) * blk)
d = np.abs(np.diff(out))
check("no click artefacts at block seams", d.max() < 0.25, f"max step {d.max():.4f}")
check("equal-power fade sums to unity",
      np.allclose(ctx.fade_in ** 2 + ctx.fade_out ** 2, 1.0, atol=1e-5))

# ------------------------------------------------------------------- engine
print("\nDSP engine")
eng = DSPEngine(48000)
eng.load(Preset(id="t", name="T", kind="dsp", dsp={"pitch": -4.0, "formant": -2.0}))
sr = 48000
t = np.arange(sr) / sr
voice = sum((1 / k) * np.sin(2 * np.pi * 150 * k * t) for k in range(1, 15)).astype(np.float32)
voice = (voice / np.abs(voice).max() * 0.4).astype(np.float32)
conv = np.concatenate([eng.convert(voice[i:i + 2880]) for i in range(0, len(voice) - 2880, 2880)])
check("engine returns finite audio", np.all(np.isfinite(conv)))
check("engine does not clip", np.abs(conv).max() <= 1.0, f"peak {np.abs(conv).max():.3f}")
from voxmorph.dsp.pitch import median_f0
f_in, f_out = median_f0(voice, sr), median_f0(conv, sr)
semis = 12 * np.log2(f_out / f_in) if f_in and f_out else 0
check("pitch shifted by the requested -4 semitones",
      abs(semis + 4) < 0.6, f"measured {semis:+.2f} st")

# ------------------------------------------------------------------ fx chain
print("\nFX chain")
cfg = FXConfig()
chain = FXChain(sr, cfg)
chain.update(cfg)
noisy = (voice + 0.05 * np.random.randn(len(voice))).astype(np.float32)
y = np.concatenate([chain.post.process(chain.pre.process(noisy[i:i + 2880]))
                    for i in range(0, len(noisy) - 2880, 2880)])
check("chain output finite", np.all(np.isfinite(y)))
check("limiter holds ceiling", np.abs(y).max() <= 1.0, f"peak {np.abs(y).max():.3f}")

# Use a fresh chain: reusing the previous one would still be flushing the
# tail of the loud signal out of its overlap-add buffer, which is correct
# behaviour but not what this check is about.
quiet_chain = FXChain(sr, cfg)
quiet_chain.update(cfg)
silence = np.zeros(2880, dtype=np.float32)
for _ in range(4):
    gated = quiet_chain.post.process(quiet_chain.pre.process(silence))
check("gate silences a silent block", np.abs(gated).max() < 1e-3,
      f"peak {np.abs(gated).max():.2e}")

# noise floor well below speech must be attenuated hard by the gate
room_tone = (0.002 * np.random.randn(2880)).astype(np.float32)
for _ in range(6):
    toned = quiet_chain.post.process(quiet_chain.pre.process(room_tone))
check("gate suppresses low-level room tone",
      np.abs(toned).max() < np.abs(room_tone).max(),
      f"{np.abs(room_tone).max():.4f} -> {np.abs(toned).max():.4f}")

# ------------------------------------------------------------------- presets
print("\nPresets and profiles")
pm = PresetManager()
check("catalog loads", len(pm.list()) >= 15, f"{len(pm.list())} presets")
check("character presets need no download",
      all(not p.needs_download for p in pm.list(kind="dsp")))
check("identity flag distinguishes preset kinds",
      not pm.get("dsp_deep_male").is_identity)

store = ProfileStore()
cfg_full = Config()
prof = VoiceProfile.capture("Test Profile", "dsp_deep_male", cfg_full.engine, cfg_full.fx)
store.save(prof)
loaded = store.load("Test Profile")
check("profile round trips", loaded is not None and loaded.preset_id == "dsp_deep_male")
store.delete("Test Profile")

# ---------------------------------------------------------------- soundboard
print("\nSoundboard")
sb = Soundboard(sr)
check("mix returns None when idle", sb.mix(512) is None)

# ------------------------------------------------------------------- config
print("\nConfig")
import tempfile
tmp = Path(tempfile.mkdtemp()) / "cfg.json"
c = Config()
c.engine.pitch_shift = 7
c.fx.reverb = 0.42
c.save(tmp)
c2 = Config.load(tmp)
check("config round trips", c2.engine.pitch_shift == 7 and abs(c2.fx.reverb - 0.42) < 1e-9)
tmp.write_text("{{{ not json")
c3 = Config.load(tmp)
check("corrupt config self-heals to defaults", c3.engine.pitch_shift == 0)

# --------------------------------------------------------------------- report
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{'=' * 60}\n{passed}/{len(results)} checks passed")
for name, ok, detail in results:
    if not ok:
        print(f"  FAILED: {name} {detail}")
sys.exit(0 if passed == len(results) else 1)
