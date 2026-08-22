"""The realtime pipeline.

Threading model - deliberately three separate concerns:

  [mic callback]  -> in_ring   (realtime thread, never blocks, never allocates)
  [worker thread] -> reads in_ring, runs pre-FX + model + post-FX -> out_ring
  [out callback]  -> drains out_ring to the virtual cable
  [monitor cb]    -> optional second copy so you can hear yourself

Neural inference can spike well past a block period. Keeping it off the audio
callbacks means a slow block causes a brief buffer dip instead of a hard
device dropout, and the ring buffers absorb the jitter.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

from ..config import Config
from ..dsp.chain import FXChain
from ..dsp.pitch import PitchTracker
from ..engines.base import ConversionParams, VoiceEngine
from ..logging_setup import get_logger
from ..metrics import Metrics
from .ringbuffer import RingBuffer

log = get_logger("stream")

StatusCb = Callable[[str], None]


class AudioPipeline:
    def __init__(self, cfg: Config, engine: VoiceEngine, metrics: Optional[Metrics] = None):
        self.cfg = cfg
        self.engine = engine
        self.metrics = metrics or Metrics()

        self.sr = cfg.audio.samplerate
        lat = cfg.latency()
        self.block = self._round_block(int(self.sr * lat["block_ms"] * 0.001))

        cap = self.block * 32
        self.in_ring = RingBuffer(cap)
        self.out_ring = RingBuffer(cap)
        self.monitor_ring = RingBuffer(cap)

        self.fx = FXChain(self.sr, cfg.fx)
        self.pitch = PitchTracker(self.sr)

        self._in_stream = None
        self._out_stream = None
        self._mon_stream = None
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self.bypass = False
        self.muted = False
        self.ptt_active = True        # True unless push-to-talk is armed
        self.recorder = None          # set by Recorder.attach()
        self.soundboard_mix: Optional[Callable[[int], np.ndarray]] = None
        self.on_status: Optional[StatusCb] = None
        self._frame_counter = 0

    # ------------------------------------------------------------------ util
    @staticmethod
    def _round_block(n: int) -> int:
        """Round to a multiple of 128 - friendlier to device buffer sizes."""
        return max(128, int(round(n / 128.0)) * 128)

    def _status(self, msg: str) -> None:
        log.info(msg)
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def block_ms(self) -> float:
        return self.block / self.sr * 1000.0

    def estimated_latency_ms(self) -> float:
        """Block + ring headroom + device buffers + STFT priming."""
        stft = (1024 - 256) / self.sr * 1000.0
        dev = 0.0
        for s in (self._in_stream, self._out_stream):
            try:
                dev += float(getattr(s, "latency", 0.0) or 0.0) * 1000.0
            except Exception:
                pass
        return self.block_ms * 2 + stft + dev

    # --------------------------------------------------------------- control
    def start(self) -> bool:
        if self.running:
            return True
        try:
            import sounddevice as sd
        except Exception as exc:
            self._status(f"Audio backend unavailable: {exc}")
            return False

        self._stop.clear()
        self.in_ring.clear()
        self.out_ring.clear()
        self.monitor_ring.clear()
        self.metrics.reset()
        self.fx.reset()
        self.engine.reset()

        a = self.cfg.audio
        extra_in = extra_out = None
        if a.exclusive_wasapi and hasattr(sd, "WasapiSettings"):
            try:
                extra_in = sd.WasapiSettings(exclusive=True)
                extra_out = sd.WasapiSettings(exclusive=True)
            except Exception:
                extra_in = extra_out = None

        try:
            self._in_stream = sd.InputStream(
                device=a.input_device, channels=1, samplerate=self.sr,
                blocksize=self.block, dtype="float32", latency="low",
                callback=self._on_input, extra_settings=extra_in,
            )
            self._out_stream = sd.OutputStream(
                device=a.output_device, channels=1, samplerate=self.sr,
                blocksize=self.block, dtype="float32", latency="low",
                callback=self._on_output, extra_settings=extra_out,
            )
        except Exception as exc:
            self._status(f"Could not open audio devices: {exc}")
            self._close_streams()
            return False

        if self.monitor_enabled:
            # Fall back to the system default output. Requiring an explicitly
            # chosen device here is what silently broke "hear yourself": the
            # field defaults to None, so the stream was never opened and the
            # toggle appeared to do nothing.
            dev = a.monitor_device
            if dev is None:
                from .devices import default_output
                d = default_output()
                dev = d.index if d else None
                if dev is not None:
                    a.monitor_device = dev
                    log.info("Monitor device defaulted to %s", d.name)
            if dev is None:
                self._status("Cannot monitor: no output device available.")
            else:
                try:
                    self._mon_stream = sd.OutputStream(
                        device=dev, channels=1, samplerate=self.sr,
                        blocksize=self.block, dtype="float32", latency="low",
                        callback=self._on_monitor,
                    )
                except Exception as exc:
                    log.warning("Monitor device unavailable: %s", exc)
                    self._status(f"Could not open the monitor device: {exc}")
                    self._mon_stream = None

        self._worker = threading.Thread(target=self._run, name="voxmorph-dsp", daemon=True)
        self._worker.start()

        try:
            self._in_stream.start()
            self._out_stream.start()
            if self._mon_stream:
                self._mon_stream.start()
        except Exception as exc:
            self._status(f"Failed to start streams: {exc}")
            self.stop()
            return False

        self.metrics.set_status(running=True)
        self.metrics.record_latency(self.estimated_latency_ms())
        self._status(f"Running - block {self.block} @ {self.sr} Hz "
                     f"(~{self.estimated_latency_ms():.0f} ms end to end)")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        self._worker = None
        self._close_streams()
        self.metrics.set_status(running=False)
        self._status("Stopped")

    def _close_streams(self) -> None:
        for attr in ("_in_stream", "_out_stream", "_mon_stream"):
            s = getattr(self, attr, None)
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)

    def restart(self) -> bool:
        was = self.running
        self.stop()
        lat = self.cfg.latency()
        self.sr = self.cfg.audio.samplerate
        self.block = self._round_block(int(self.sr * lat["block_ms"] * 0.001))
        self.fx = FXChain(self.sr, self.cfg.fx)
        for setter in ("set_timing",):
            fn = getattr(self.engine, setter, None)
            if callable(fn):
                fn(lat["context_ms"], lat["crossfade_ms"])
        return self.start() if was else True

    # ------------------------------------------------------------- callbacks
    def _on_input(self, indata, frames, time_info, status) -> None:
        if status:
            self.metrics.add_dropout()
        mono = indata[:, 0] if indata.ndim > 1 else indata
        gain = 10.0 ** (self.cfg.audio.input_gain_db / 20.0)
        self.in_ring.write(mono * gain)

    def _on_output(self, outdata, frames, time_info, status) -> None:
        if status:
            self.metrics.add_dropout()
        data = self.out_ring.read(frames)
        if self.muted or not self.ptt_active:
            data = np.zeros(frames, dtype=np.float32)
        gain = 10.0 ** (self.cfg.audio.output_gain_db / 20.0)
        outdata[:, 0] = data * gain

    def _on_monitor(self, outdata, frames, time_info, status) -> None:
        gain = 10.0 ** (self.cfg.audio.monitor_volume_db / 20.0)
        outdata[:, 0] = self.monitor_ring.read(frames) * gain

    @property
    def monitor_enabled(self) -> bool:
        """Single source of truth - persisted in the config, not a stray flag."""
        return self.cfg.audio.monitor_enabled

    @monitor_enabled.setter
    def monitor_enabled(self, value: bool) -> None:
        self.cfg.audio.monitor_enabled = bool(value)

    # ------------------------------------------------------------ processing
    def _run(self) -> None:
        log.info("DSP worker started (block=%d, %.1f ms)", self.block, self.block_ms)
        while not self._stop.is_set():
            block = self.in_ring.wait_read(self.block, timeout=0.25)
            if block is None:
                continue
            t0 = time.perf_counter()
            try:
                out = self._process(block)
            except Exception as exc:
                log.exception("Processing error: %s", exc)
                out = np.zeros(self.block, dtype=np.float32)

            elapsed = (time.perf_counter() - t0) * 1000.0
            self.metrics.record_block(elapsed, self.block_ms,
                                      getattr(self.engine, "last_infer_ms", 0.0))
            self.out_ring.write(out)
            if self.monitor_enabled:
                self.monitor_ring.write(out)
            if self.recorder is not None:
                self.recorder.feed(block, out)
        log.info("DSP worker stopped")

    def _process(self, block: np.ndarray) -> np.ndarray:
        in_peak = float(np.max(np.abs(block))) if len(block) else 0.0
        in_rms = float(np.sqrt(np.mean(block ** 2))) if len(block) else 0.0

        if self.bypass:
            self.metrics.record_levels(in_rms, in_peak, in_rms, in_peak)
            return block.astype(np.float32)

        # 1. clean up before the model sees it
        y = self.fx.pre.process(block)

        # 2. track pitch for auto octave matching + the HUD
        self._frame_counter += 1
        if self._frame_counter % 2 == 0:
            f0 = self.pitch.push(y)
            if f0 > 0:
                offset = 0.0
                upd = getattr(self.engine, "update_auto_pitch", None)
                if callable(upd):
                    offset = upd(self.pitch.median or f0)
                self.metrics.record_pitch(f0, offset)

        # 3. the voice model
        y = self.engine.convert(y)

        # 4. tone, dynamics and creative FX
        y = self.fx.post.process(y)

        # 5. soundboard is mixed post-chain so clips play back unmodified
        if self.soundboard_mix is not None:
            clip = self.soundboard_mix(len(y))
            if clip is not None and len(clip) == len(y):
                y = np.clip(y + clip, -1.0, 1.0)

        if len(y) != self.block:
            y = (np.concatenate([y, np.zeros(self.block - len(y), dtype=np.float32)])
                 if len(y) < self.block else y[: self.block])

        out_peak = float(np.max(np.abs(y))) if len(y) else 0.0
        out_rms = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
        self.metrics.record_levels(in_rms, in_peak, out_rms, out_peak)
        self._update_spectrum(y)
        return y.astype(np.float32)

    def _update_spectrum(self, y: np.ndarray, bands: int = 32) -> None:
        if self._frame_counter % 3:
            return
        n = min(1024, len(y))
        if n < 64:
            return
        spec = np.abs(np.fft.rfft(y[:n] * np.hanning(n)))
        edges = np.geomspace(1, len(spec) - 1, bands + 1).astype(int)
        vals = [float(20 * np.log10(max(spec[a:max(b, a + 1)].mean(), 1e-9)))
                for a, b in zip(edges[:-1], edges[1:])]
        self.metrics.record_spectrum(vals)

    # ------------------------------------------------------------ live edits
    def apply_config(self, formant_semis: float = 0.0, pitch_semis: float = 0.0) -> None:
        """Push UI changes into the running chain without restarting audio."""
        self.fx.update(self.cfg.fx, formant_semis, pitch_semis)
        e = self.cfg.engine
        self.engine.set_params(ConversionParams(
            pitch_shift=e.pitch_shift,
            formant_shift=e.formant_shift,
            index_rate=e.index_rate,
            protect=e.protect,
            rms_mix_rate=e.rms_mix_rate,
            f0_method=e.f0_method,
            auto_pitch=e.auto_pitch_match,
            target_f0=self.engine.params.target_f0,
        ))

    def swap_engine(self, engine: VoiceEngine) -> None:
        old = self.engine
        self.engine = engine
        self.engine.reset()
        try:
            old.unload()
        except Exception:
            pass
        self.metrics.set_status(engine=engine.caps.display_name)
