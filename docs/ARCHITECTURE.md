# Architecture

## Layers

```
  ui/            PySide6 window, widgets, theme          (replaceable)
      │
  app.py         VoxMorphApp controller - UI-free        (the real API)
      │
  ┌───┴──────────┬──────────────┬───────────────┬─────────────┐
audio/          engines/       presets/        updater/     dsp/
pipeline        rvc/seedvc/    catalog +       GitHub       filters,
devices         dsp + registry download        releases     dynamics,
ringbuffer                                                  spectral, fx
```

`app.py` owns everything and knows nothing about Qt. The GUI, the CLI and any future headless service all drive the same controller.

## Realtime threading

Three concerns, deliberately separated:

| Thread | Job | Constraint |
|---|---|---|
| Input callback | mic → `in_ring` | Realtime priority. Never blocks, never allocates. |
| DSP worker | `in_ring` → pre-FX → model → post-FX → `out_ring` | May spike past a block period. |
| Output callback | `out_ring` → virtual cable | Realtime priority. |

Neural inference is bursty — a GC pause or a cold CUDA kernel can take 3× the average. If that ran inside the audio callback, PortAudio would report an underrun and you would hear a click. Off the callback, the ring buffer absorbs it and you hear nothing.

Ring buffers are fixed-capacity. On overflow they drop the oldest samples and increment a counter shown in the HUD, rather than growing unboundedly and adding latency.

## Chunked neural inference

Neural VC models want surrounding context; a realtime app only has the past. Standard solution:

```
[ ------- left context ------- | block ]
                                ^^^^^^^ the only part emitted
```

Each pass re-infers the context so the model's internal state stays consistent. Consecutive outputs are **equal-power crossfaded** (`sin²+cos²=1`) over a 20–64 ms window so the seam is inaudible. `StreamingContext` in `engines/base.py` implements this once and both neural engines share it.

Verified in `tests/test_integration.py`: maximum sample-to-sample step across block seams stays under 0.13 for a continuous sine.

## Signal chain order

```
input → HPF → denoise → gate → [VOICE MODEL] → formant/pitch
      → character → EQ → compressor → de-esser
      → chorus → echo → reverb → limiter → output
```

Cleanup before the model (models hallucinate on room tone), tone and dynamics after it (the model output has its own spectral balance we want the final say over).

## Spectral processing

`dsp/spectral.py` does denoise, formant warping and pitch shifting in a **single STFT pass** (1024 / hop 256, sqrt-Hann, COLA-normalised).

- **Denoise** — minimum-statistics noise floor with asymmetric tracking (fast down, slow up), Wiener-style soft mask to avoid musical noise.
- **Formant warp** — cepstral liftering separates the spectral envelope (vocal tract) from the excitation (glottal source); the envelope alone is resampled. This is what makes pitch and vocal-tract size independent.
- **Pitch shift** — phase vocoder with true-frequency estimation from inter-frame phase deviation, then bin remapping with phase accumulation. Frequency-domain only, so it stays block-aligned.

## JIT kernels

`dsp/kernels.py` holds the loops that genuinely cannot be vectorised because they contain feedback: envelope follower, gate, limiter, reverb combs and allpasses. They are `@njit(cache=True, fastmath=True)`.

If numba is unavailable the decorator degrades to a no-op and the pure-Python versions run — slower, but the app still works. `warmup()` is called on a background thread at startup so the first audio block never pays compilation cost.

## Engine fallback

`engines/registry.py` tries `rvc → seedvc → dsp`. Any `EngineError` (no GPU, missing dependency, corrupt checkpoint) drops to the next tier and surfaces the reason in the status bar. The app never fails to start because of a model problem.

## Update flow

```
CI builds installer ──► GitHub Release (SHA-256 in body)
                              │
      app launch ──► GET /releases ──► semver compare
                              │
                     newer? ──► banner ──► download ──► verify SHA-256
                                                             │
                                                     match? ──► run installer
                                                     no?    ──► discard + warn
```

Two channels: `stable` ignores prereleases; `ai-nightly` includes them, so automated CI builds reach opt-in users without disturbing everyone else. Semver ordering puts prereleases *below* the same release version, so a nightly can never mask a stable release.

## Adding an engine

1. Subclass `VoiceEngine` in `engines/`, set `caps`, implement `load()` and `convert()`.
2. Use `StreamingContext` for chunking if it is a neural model.
3. Register it in `ENGINES` in `registry.py`.

That is all — the UI, config, presets and metrics pick it up automatically.
