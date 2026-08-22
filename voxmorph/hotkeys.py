"""Global hotkeys - they work while a game or Discord has focus.

Uses the `keyboard` package on Windows. It is optional: if it is missing or
blocked (some anti-cheat drivers refuse low-level hooks), hotkeys silently
disable themselves and the rest of the app keeps working.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

from .logging_setup import get_logger

log = get_logger("hotkeys")

try:
    import keyboard  # type: ignore
    HAVE_KEYBOARD = True
except Exception:  # pragma: no cover
    keyboard = None  # type: ignore
    HAVE_KEYBOARD = False


class HotkeyManager:
    def __init__(self) -> None:
        self._handles: Dict[str, object] = {}
        self._held: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self.enabled = HAVE_KEYBOARD
        if not HAVE_KEYBOARD:
            log.warning("`keyboard` unavailable - global hotkeys disabled. "
                        "Install with: pip install keyboard")

    # ------------------------------------------------------------------ bind
    def bind(self, combo: str, callback: Callable[[], None]) -> bool:
        """Bind a press action, e.g. 'ctrl+alt+m'."""
        if not self.enabled or not combo:
            return False
        with self._lock:
            self.unbind(combo)
            try:
                self._handles[combo] = keyboard.add_hotkey(
                    combo, self._safe(callback), suppress=False, trigger_on_release=False
                )
                log.info("Bound hotkey %s", combo)
                return True
            except Exception as exc:
                log.error("Could not bind '%s': %s", combo, exc)
                return False

    def bind_hold(self, combo: str, on_press: Callable[[], None],
                  on_release: Callable[[], None]) -> bool:
        """Bind a press-and-hold action (push-to-talk / push-to-mute)."""
        if not self.enabled or not combo:
            return False
        with self._lock:
            try:
                key = combo.split("+")[-1].strip()
                p = keyboard.on_press_key(key, lambda _e: self._safe(on_press)(), suppress=False)
                r = keyboard.on_release_key(key, lambda _e: self._safe(on_release)(), suppress=False)
                self._held[combo] = (p, r)
                log.info("Bound hold-hotkey %s", combo)
                return True
            except Exception as exc:
                log.error("Could not bind hold '%s': %s", combo, exc)
                return False

    def unbind(self, combo: str) -> None:
        h = self._handles.pop(combo, None)
        if h is not None:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        held = self._held.pop(combo, None)
        if held:
            for hook in held:
                try:
                    keyboard.unhook(hook)
                except Exception:
                    pass

    def unbind_all(self) -> None:
        with self._lock:
            for combo in list(self._handles):
                self.unbind(combo)
            for combo in list(self._held):
                self.unbind(combo)

    @staticmethod
    def _safe(fn: Callable[[], None]) -> Callable[[], None]:
        def wrapper(*_a, **_kw):
            try:
                fn()
            except Exception as exc:
                log.exception("Hotkey handler failed: %s", exc)
        return wrapper

    # --------------------------------------------------------------- helpers
    def apply(self, cfg, actions: Dict[str, Callable[[], None]],
              ptt: Optional[tuple] = None) -> None:
        """Rebind everything from a HotkeyConfig.

        actions maps config field names -> callables, e.g.
            {'toggle_mute': fn, 'next_preset': fn, ...}
        ptt is (on_press, on_release) for push-to-talk.
        """
        self.unbind_all()
        if not cfg.enabled or not self.enabled:
            return
        for field, fn in actions.items():
            combo = getattr(cfg, field, "")
            if combo:
                self.bind(combo, fn)
        if ptt and cfg.push_to_talk:
            self.bind_hold(cfg.push_to_talk, ptt[0], ptt[1])
