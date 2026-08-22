/* VoxMorph — marketing + download site.
   Hash-routed SPA. Live GitHub Releases data with graceful fallback.
   Demo audio is real: neural TTS source run through the shipping DSP engine. */

'use strict';

/* ── CONFIG ──────────────────────────────────────────────────────────────
   Change owner/repo and everything else follows.                        */
const CONFIG = {
  owner: 'joeoeiur-cell',
  repo: 'voxmorph-voice-changer',
  fallback: { version: '1.0.0', sizeMB: 180, date: '2026-08-22', sha256: '', url: '#' },
};

/* Demo voices — each maps to a real rendered clip in /audio */
const DEMOS = [
  { id: 'deep_male',    name: 'Deep Male',    tag: 'Masculine', note: 'F0 92 Hz · vocal tract 10% longer' },
  { id: 'giant',        name: 'Giant',        tag: 'Masculine', note: 'F0 72 Hz · tract 22% longer, dark tilt' },
  { id: 'radio_host',   name: 'Radio Host',   tag: 'Broadcast', note: 'F0 108 Hz · pressed source, full body' },
  { id: 'young_female', name: 'Young Female', tag: 'Feminine',  note: 'F0 208 Hz · tract 18% shorter, breathier' },
  { id: 'soft_female',  name: 'Soft Female',  tag: 'Feminine',  note: 'F0 194 Hz · more aspiration, softer source' },
  { id: 'kid',          name: 'Kid',          tag: 'Feminine',  note: 'F0 262 Hz · tract 34% shorter' },
  { id: 'demon',        name: 'Demon',        tag: 'Character', note: 'F0 62 Hz · extreme tract lengthening' },
  { id: 'robot',        name: 'Robot',        tag: 'Character', note: 'Ring-modulated monotone' },
  { id: 'telephone',    name: 'Telephone',    tag: 'Broadcast', note: 'Band-limited 300 Hz – 3.4 kHz' },
];

const FEATURES = [
  ['fingerprint', 'Identity voices', 'Speaker-locked neural conversion. The same person out, whoever talks in.'],
  ['zap', 'Instant character presets', '15 built in. No GPU, no download, ~2 ms.'],
  ['scan-face', 'Zero-shot cloning', 'Clone a voice from a 15-second clip. No training.'],
  ['timer', 'Realtime latency', 'Four profiles, from ~55 ms to ~250 ms.'],
  ['sliders-horizontal', 'Studio rack', 'Denoise, gate, compressor, de-esser, EQ, limiter.'],
  ['audio-waveform', 'Creative FX', 'Reverb, echo, chorus, robot, megaphone, monster.'],
  ['keyboard', 'Global hotkeys', 'Push-to-talk, mute, bypass, panic stop — in any app.'],
  ['crosshair', 'Auto pitch match', 'Aligns your pitch to the target voice automatically.'],
  ['refresh-cw', 'Verified updates', 'SHA-256 checked installers. Stable and nightly channels.'],
];

const FAQ = [
  ['Is it really free?', 'Yes. MIT licensed, no account, no telemetry, no paywalled voices.'],
  ['Do I need a GPU?', 'Not for character presets — they run on any CPU in about 2 ms. Identity voices use a neural model and want an NVIDIA GPU (RTX 2060 or better) to stay realtime.'],
  ['Why do I need a virtual audio cable?', 'VoxMorph produces audio. A virtual cable presents that audio to Discord, OBS or your game as if it were a microphone. VB-CABLE is free and takes a minute to install.'],
  ['Does it work with Discord, OBS and games?', 'Anything that lets you choose an input device. Turn off Discord\u2019s Krisp noise suppression — it fights VoxMorph\u2019s own processing.'],
  ['How much latency will I really get?', 'Character presets add about 2 ms. Identity voices land between 40 and 150 ms depending on the profile and your GPU. The in-app HUD shows your actual number live.'],
  ['Can I add my own voice models?', 'Yes. Drop any RVC .pth file (and its .index) into the models folder and it appears under My Voices.'],
  ['Is my audio sent anywhere?', 'No. Everything is processed locally. The only network request is the update check against GitHub.'],
];

const CREDITS = [
  ['RVC-Project/Retrieval-based-Voice-Conversion-WebUI', 'Identity conversion architecture'],
  ['daswer123/rvc-python', 'RVC inference as a Python package'],
  ['deiteris/voice-changer', 'Realtime streaming design'],
  ['Plachtaa/seed-vc', 'Zero-shot voice cloning'],
  ['IAHispano/Applio', 'RVC training ecosystem'],
];

/* ── ICONS ─────────────────────────────────────────────────────────────── */
const ICONS = {
  fingerprint: '<path d="M12 11a4 4 0 0 0-4 4c0 1.5-.5 3-1 4"/><path d="M12 3a8 8 0 0 0-8 8c0 2 .5 4 1 5.5"/><path d="M12 3a8 8 0 0 1 8 8c0 1.5-.2 3-.5 4.5"/><path d="M12 7a4 4 0 0 1 4 4c0 2-.5 4-1 6"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  'scan-face': '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
  timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/>',
  'sliders-horizontal': '<line x1="21" y1="4" x2="14" y2="4"/><line x1="10" y1="4" x2="3" y2="4"/><line x1="21" y1="12" x2="12" y2="12"/><line x1="8" y1="12" x2="3" y2="12"/><line x1="21" y1="20" x2="16" y2="20"/><line x1="12" y1="20" x2="3" y2="20"/><line x1="14" y1="2" x2="14" y2="6"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="16" y1="18" x2="16" y2="22"/>',
  'audio-waveform': '<path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4a2 2 0 0 1 2-2"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 14h6"/>',
  crosshair: '<circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/>',
  'refresh-cw': '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  'chevron-down': '<polyline points="6 9 12 15 18 9"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  arrow: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
};
const ic = (n, c = 'w-5 h-5') =>
  `<svg class="${c}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ''}</svg>`;

/* ── GITHUB RELEASE DATA ────────────────────────────────────────────────── */
const Release = { data: null };

async function fetchRelease() {
  try {
    // /releases/latest ignores prereleases and 404s on a repo that only has
    // nightly builds, so list releases and pick the newest stable one, or the
    // newest prerelease when no stable release exists yet.
    const r = await fetch(`https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/releases?per_page=20`,
      { headers: { Accept: 'application/vnd.github+json' } });
    if (!r.ok) throw 0;
    const all = (await r.json()).filter(x => !x.draft);
    const rel = all.find(x => !x.prerelease) || all[0];
    if (!rel) throw 0;
    const asset = (rel.assets || []).find(a => /\.(exe|msi)$/i.test(a.name)) || rel.assets?.[0];
    const sha = (rel.body || '').match(/\b([a-f0-9]{64})\b/i);
    Release.data = {
      version: (rel.tag_name || '').replace(/^v/, '') || CONFIG.fallback.version,
      sizeMB: asset ? Math.round(asset.size / 1048576) : CONFIG.fallback.sizeMB,
      date: (rel.published_at || '').slice(0, 10) || CONFIG.fallback.date,
      sha256: sha ? sha[1].toLowerCase() : '',
      url: asset?.browser_download_url || rel.html_url || CONFIG.fallback.url,
      notes: rel.body || '', prerelease: !!rel.prerelease, live: true,
    };
  } catch {
    Release.data = { ...CONFIG.fallback, live: false };
  }
  paintRelease();
}

function paintRelease() {
  const d = Release.data; if (!d) return;
  document.querySelectorAll('[data-version]').forEach(e => e.textContent = 'v' + d.version);
  document.querySelectorAll('[data-size]').forEach(e => e.textContent = d.sizeMB + ' MB');
  document.querySelectorAll('[data-date]').forEach(e => e.textContent = d.date);
  document.querySelectorAll('[data-link]').forEach(e => e.href = d.url);
  document.querySelectorAll('[data-sha]').forEach(e => {
    e.textContent = d.sha256 || 'See the release notes on GitHub';
    e.classList.remove('skeleton');
  });
}

/* ── AUDIO PLAYER ───────────────────────────────────────────────────────
   One shared <audio>. Clicking a voice plays the converted clip; the
   A/B switch flips between the untouched source and the conversion.    */
const Player = {
  el: null, current: null, mode: 'converted',

  audio() {
    if (!this.el) {
      this.el = new Audio();
      this.el.preload = 'none';
      this.el.addEventListener('ended', () => this.paint(null));
      this.el.addEventListener('error', () => this.paint(null));
    }
    return this.el;
  },

  srcFor(id) {
    const key = this.mode === 'original' ? 'original' : id;
    // Standalone preview builds inline the clips as data URIs; the deployed
    // site serves them as files from /audio.
    const inline = (typeof window !== 'undefined' && window.AUDIO_DATA) || null;
    return (inline && inline[key]) ? inline[key] : `audio/${key}.mp3`;
  },

  toggle(id) {
    const a = this.audio();
    if (this.current === id && !a.paused) { a.pause(); this.paint(null); return; }
    this.current = id;
    a.src = this.srcFor(id);
    a.currentTime = 0;
    a.play().then(() => this.paint(id)).catch(() => this.paint(null));
  },

  setMode(mode) {
    this.mode = mode;
    document.querySelectorAll('[data-mode]').forEach(b => {
      const on = b.dataset.mode === mode;
      b.className = `flex-1 px-4 py-2 rounded-lg text-sm font-semibold transition ${
        on ? 'bg-accent text-bg shadow-sm' : 'text-muted hover:text-ink'}`;
      b.setAttribute('aria-pressed', String(on));
    });
    if (this.current) {
      const a = this.audio();
      const was = !a.paused;
      a.src = this.srcFor(this.current);
      if (was) a.play().catch(() => {});
    }
  },

  paint(activeId) {
    document.querySelectorAll('[data-voice]').forEach(row => {
      const on = row.dataset.voice === activeId;
      row.classList.toggle('ring-1', on);
      row.classList.toggle('ring-accent', on);
      const btn = row.querySelector('.play-btn');
      if (btn) btn.innerHTML = ic(on ? 'pause' : 'play', 'w-4 h-4');
      const bars = row.querySelector('.bars');
      if (bars) bars.classList.toggle('playing', on);
    });
  },

  stop() { if (this.el) { this.el.pause(); } this.current = null; this.paint(null); },
};

/* ── HERO WAVEFORM ──────────────────────────────────────────────────────── */
function heroWave() {
  const c = document.getElementById('wave'); if (!c) return;
  const ctx = c.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let t = 0;
  (function draw() {
    const w = c.width = c.clientWidth * devicePixelRatio;
    const h = c.height = c.clientHeight * devicePixelRatio;
    ctx.clearRect(0, 0, w, h);
    const N = 64, bw = w / N;
    for (let i = 0; i < N; i++) {
      const rel = Math.abs(i - N / 2) / (N / 2);
      const env = Math.max(0.05, 1 - rel * rel * 1.1);
      const wav = 0.5 + 0.5 * Math.sin(t * .018 + i * .5) * Math.sin(t * .011 + i * .19);
      const bh = h * .6 * env * (.2 + .8 * wav);
      const g = ctx.createLinearGradient(0, h, 0, h - bh);
      g.addColorStop(0, 'rgba(14,116,144,0.5)'); g.addColorStop(1, 'rgba(34,211,238,0.9)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.roundRect(i * bw + bw * .22, h - bh, bw * .56, bh, bw * .28);
      ctx.fill();
    }
    t++;
    if (!reduced) requestAnimationFrame(draw);
  })();
}

/* ── SHARED BITS ────────────────────────────────────────────────────────── */
const section = (inner, cls = '') =>
  `<section class="mx-auto max-w-5xl px-6 py-20 sm:py-28 ${cls}">${inner}</section>`;

const heading = (title, sub) => `
  <div class="max-w-2xl">
    <h2 class="text-3xl sm:text-4xl font-bold tracking-tight">${title}</h2>
    ${sub ? `<p class="mt-3 text-muted leading-relaxed">${sub}</p>` : ''}
  </div>`;

const cta = (label = 'Download for Windows') => {
  const d = Release.data || CONFIG.fallback;
  return `<a data-link href="${d.url}" class="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-accent text-bg font-bold text-sm hover:bg-accent/90 transition">
    ${ic('download', 'w-4 h-4')} ${label}
    <span class="mono text-xs font-medium opacity-75" data-version>v${d.version}</span>
  </a>`;
};

/* ── HOME ───────────────────────────────────────────────────────────────── */
function pageHome() {
  const d = Release.data || CONFIG.fallback;

  const hero = `
  <section class="relative overflow-hidden">
    <div class="absolute inset-x-0 bottom-0 h-64 opacity-25 pointer-events-none"><canvas id="wave" class="w-full h-full"></canvas></div>
    <div class="absolute inset-0 bg-gradient-to-b from-transparent via-bg/70 to-bg pointer-events-none"></div>
    <div class="relative mx-auto max-w-5xl px-6 pt-24 pb-28 sm:pt-32 sm:pb-36 text-center">
      <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-border bg-surface text-xs text-muted">
        <span class="w-1.5 h-1.5 rounded-full bg-good"></span> Free · open source · runs entirely on your machine
      </div>
      <h1 class="mt-7 text-[2.6rem] leading-[1.05] sm:text-6xl font-extrabold tracking-tight">
        Sound like someone else.<br><span class="text-accent">Not like yourself, higher.</span>
      </h1>
      <p class="mt-6 text-lg text-muted max-w-xl mx-auto leading-relaxed">
        A realtime voice changer with speaker-locked preset voices — so the person people hear stays the same, whoever is at the mic.
      </p>
      <div class="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
        ${cta()}
        <a href="https://github.com/${CONFIG.owner}/${CONFIG.repo}" target="_blank" rel="noopener"
           class="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-border bg-surface text-sm font-semibold hover:border-accent/60 transition">
          ${ic('github', 'w-4 h-4')} Source on GitHub
        </a>
      </div>
      <p class="mt-5 text-xs text-muted mono">Windows 10/11 · <span data-size>${d.sizeMB} MB</span> · MIT</p>
    </div>
  </section>`;

  const demo = `
  <div class="border-y border-border bg-surface/40">
    ${section(`
      ${heading('Hear it', 'One recording, every preset. Flip the switch to compare the untouched source against the converted output.')}
      <div class="mt-8 rounded-2xl border border-border bg-surface overflow-hidden">
        <div class="p-2 border-b border-border bg-surface2/60">
          <div class="flex gap-1 rounded-xl bg-bg/60 p-1 max-w-sm">
            <button data-mode="original" onclick="Player.setMode('original')" aria-pressed="false"
              class="flex-1 px-4 py-2 rounded-lg text-sm font-semibold text-muted hover:text-ink transition">Original</button>
            <button data-mode="converted" onclick="Player.setMode('converted')" aria-pressed="true"
              class="flex-1 px-4 py-2 rounded-lg text-sm font-semibold bg-accent text-bg shadow-sm transition">Converted</button>
          </div>
        </div>
        <div class="divide-y divide-border">
          ${DEMOS.map(v => `
          <div data-voice="${v.id}" class="flex items-center gap-4 px-4 sm:px-5 py-3.5 hover:bg-surface2/50 transition">
            <button class="play-btn shrink-0 w-10 h-10 rounded-full bg-accent/12 text-accent border border-accent/30 grid place-items-center hover:bg-accent/20 transition"
                    onclick="Player.toggle('${v.id}')" aria-label="Play ${v.name}">${ic('play', 'w-4 h-4')}</button>
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-2 flex-wrap">
                <span class="font-semibold text-sm">${v.name}</span>
                <span class="text-[10px] uppercase tracking-wider text-muted">${v.tag}</span>
              </div>
              <div class="text-xs text-muted mt-0.5 truncate">${v.note}</div>
            </div>
            <div class="bars hidden sm:flex items-end gap-[3px] h-6 w-24 shrink-0" aria-hidden="true">
              ${Array.from({ length: 14 }, (_, i) => `<span style="--i:${i}" class="w-1 rounded-full bg-accent/35"></span>`).join('')}
            </div>
          </div>`).join('')}
        </div>
      </div>
      <div class="mt-6 grid sm:grid-cols-3 gap-4">
        ${[
          ['Fundamental frequency', 'The pitch of the vocal folds. Female/male ratio is about 1.5–1.6.'],
          ['Vocal tract length', 'Heard as formant positions. Female formants sit ~18% higher — and F1 scales less than F2/F3, so the warp is piecewise, not a single multiplier.'],
          ['Source spectral tilt', 'How fast energy falls off with frequency. The cue most voice changers ignore, and why they sound like a pitch knob.'],
        ].map(([t, s], i) => `
        <div class="rounded-xl border border-border bg-surface2/40 p-4">
          <div class="mono text-[10px] text-accent font-bold">CUE ${i + 1}</div>
          <div class="mt-1 text-sm font-semibold">${t}</div>
          <p class="mt-1 text-xs text-muted leading-relaxed">${s}</p>
        </div>`).join('')}
      </div>
      <p class="mt-4 text-xs text-muted leading-relaxed">
        Clips are real output: a neural TTS recording resynthesised through the WORLD vocoder,
        modelling all three cues independently. Measured on this recording it scores
        <strong class="text-ink">1.4–2.9 dB higher harmonics-to-noise ratio</strong> than the
        phase-vocoder approach, which is the difference between “a person” and “a pitch shifter”.
        Identity-voice samples arrive with the first consented voice pack.
      </p>
    `)}
  </div>`;

  const different = section(`
    ${heading('Preset voices, not pitch sliders',
      'Most voice changers move your pitch around, so you still sound like you. Identity voices replace your timbre outright.')}
    <div class="mt-10 grid md:grid-cols-2 gap-4">
      <div class="rounded-2xl border border-border bg-surface p-6">
        <div class="text-xs font-bold uppercase tracking-wider text-muted">Pitch shifting</div>
        <ul class="mt-4 space-y-3 text-sm text-muted">
          ${['You still sound like you', 'A different result for every speaker', 'Chipmunk artefacts when pushed']
            .map(t => `<li class="flex gap-2.5">${ic('x', 'w-4 h-4 text-bad shrink-0 mt-0.5')}<span>${t}</span></li>`).join('')}
        </ul>
      </div>
      <div class="rounded-2xl border border-accent/40 bg-accent/[0.03] p-6">
        <div class="text-xs font-bold uppercase tracking-wider text-accent">VoxMorph identity voices</div>
        <ul class="mt-4 space-y-3 text-sm">
          ${['Neural timbre replacement, not a filter', 'The <strong>same voice</strong> for every speaker', 'Pitch and vocal-tract size move independently']
            .map(t => `<li class="flex gap-2.5">${ic('check', 'w-4 h-4 text-good shrink-0 mt-0.5')}<span>${t}</span></li>`).join('')}
        </ul>
      </div>
    </div>
    <div class="mt-4 rounded-2xl border border-border bg-surface2/50 p-5 text-sm text-muted leading-relaxed">
      <strong class="text-ink">Why that works:</strong> the model splits speech into <em>content</em> — the words and pitch contour, taken from your mic — and <em>identity</em>, which lives entirely in a trained decoder. Your voice never supplies the identity, so the output is whoever the model was trained on.
    </div>
  `);

  const features = `
  <div class="border-y border-border bg-surface/40">
    ${section(`
      ${heading('What you get')}
      <div class="mt-10 grid sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-9">
        ${FEATURES.map(([i, t, s]) => `
        <div>
          <div class="w-9 h-9 rounded-xl bg-accent/10 text-accent grid place-items-center">${ic(i, 'w-4.5 h-4.5')}</div>
          <h3 class="mt-3.5 font-semibold text-sm">${t}</h3>
          <p class="mt-1.5 text-sm text-muted leading-relaxed">${s}</p>
        </div>`).join('')}
      </div>
    `)}
  </div>`;

  const how = section(`
    ${heading('Set up once', 'Four steps, about five minutes.')}
    <ol class="mt-10 grid sm:grid-cols-2 gap-x-10 gap-y-7">
      ${[
        ['Install VoxMorph', 'Plus VB-CABLE, the free virtual audio cable.'],
        ['Choose a voice', 'From the built-in library, or import your own model.'],
        ['Point your app at the cable', 'In Discord: Input Device → CABLE Output.'],
        ['Press Start', 'You are heard as the target voice.'],
      ].map(([t, s], i) => `
      <li class="flex gap-4">
        <span class="shrink-0 w-7 h-7 rounded-lg bg-surface2 border border-border grid place-items-center mono text-xs font-bold text-accent">${i + 1}</span>
        <div><div class="font-semibold text-sm">${t}</div><div class="mt-1 text-sm text-muted">${s}</div></div>
      </li>`).join('')}
    </ol>
    <div class="mt-9 rounded-2xl border border-border bg-surface p-5 flex flex-wrap items-center justify-center gap-x-3 gap-y-2 mono text-xs text-muted">
      <span class="px-3 py-1.5 rounded-lg bg-surface2">Microphone</span>${ic('arrow', 'w-3.5 h-3.5 text-accent')}
      <span class="px-3 py-1.5 rounded-lg bg-accent/12 text-accent font-semibold">VoxMorph</span>${ic('arrow', 'w-3.5 h-3.5 text-accent')}
      <span class="px-3 py-1.5 rounded-lg bg-surface2">Virtual cable</span>${ic('arrow', 'w-3.5 h-3.5 text-accent')}
      <span class="px-3 py-1.5 rounded-lg bg-surface2">Discord · OBS · game</span>
    </div>
  `);

  const perf = `
  <div class="border-y border-border bg-surface/40">
    ${section(`
      ${heading('Fast enough to talk over', 'Inference runs off the audio callbacks, so a slow block dips the buffer instead of dropping out.')}
      <div class="mt-9 grid sm:grid-cols-3 gap-4">
        ${[['40–150 ms', 'end-to-end latency'], ['~8 ms', 'DSP per 60 ms block (p95)'], ['< 1 cent', 'pitch tracking error']]
          .map(([n, l]) => `<div class="rounded-2xl border border-border bg-surface p-6">
            <div class="mono text-3xl font-bold text-accent">${n}</div>
            <div class="mt-1.5 text-xs text-muted">${l}</div></div>`).join('')}
      </div>
      <div class="mt-4 overflow-x-auto rounded-2xl border border-border">
        <table class="w-full text-sm min-w-[440px]">
          <thead><tr class="bg-surface2/70 text-left text-[11px] uppercase tracking-wider text-muted">
            <th class="px-5 py-3 font-semibold">Profile</th><th class="px-5 py-3 font-semibold">Latency</th><th class="px-5 py-3 font-semibold">Best for</th>
          </tr></thead>
          <tbody class="divide-y divide-border bg-surface">
            ${[['Ultra-Low', '~55 ms', 'Strong GPUs, fast conversation'],
               ['Low', '~90 ms', 'The default — gaming and chat'],
               ['Balanced', '~150 ms', 'Modest GPUs, streaming'],
               ['Max Quality', '~250 ms', 'Recording and content creation']]
              .map(r => `<tr><td class="px-5 py-3 font-semibold">${r[0]}</td><td class="px-5 py-3 mono text-accent">${r[1]}</td><td class="px-5 py-3 text-muted">${r[2]}</td></tr>`).join('')}
          </tbody>
        </table>
      </div>
    `)}
  </div>`;

  const faq = section(`
    ${heading('Questions')}
    <div class="mt-8 rounded-2xl border border-border bg-surface divide-y divide-border overflow-hidden">
      ${FAQ.map(([q, a], i) => `
      <div class="faq-item" id="q${i}">
        <button class="w-full flex items-center justify-between gap-4 px-5 py-4 text-left text-sm font-semibold hover:bg-surface2/40 transition"
                onclick="const e=document.getElementById('q${i}');e.classList.toggle('open');this.setAttribute('aria-expanded',e.classList.contains('open'))" aria-expanded="false">
          <span>${q}</span><span class="faq-chevron text-muted shrink-0">${ic('chevron-down', 'w-4 h-4')}</span>
        </button>
        <div class="faq-answer"><div><p class="px-5 pb-4 text-sm text-muted leading-relaxed">${a}</p></div></div>
      </div>`).join('')}
    </div>
  `);

  const ethics = `
  <div class="mx-auto max-w-5xl px-6 pb-20">
    <div class="rounded-2xl border border-warn/40 bg-warn/[0.04] p-6 flex gap-4">
      <span class="text-warn shrink-0 mt-0.5">${ic('alert', 'w-5 h-5')}</span>
      <div class="text-sm leading-relaxed">
        <strong class="text-warn">Use it responsibly.</strong>
        <span class="text-muted">Only clone voices you have permission to use. Impersonation for fraud, harassment, or bypassing voice authentication is illegal in many places. VoxMorph ships no third-party voice models — you bring your own, and every catalog entry records its license and consent status.</span>
      </div>
    </div>
  </div>`;

  const credits = `
  <div class="border-t border-border bg-surface/40">
    ${section(`
      ${heading('Built on open source')}
      <div class="mt-8 grid sm:grid-cols-2 gap-x-8 gap-y-4">
        ${CREDITS.map(([r, role]) => `
        <a href="https://github.com/${r}" target="_blank" rel="noopener" class="group flex items-start gap-3 py-2">
          <span class="text-muted group-hover:text-accent transition shrink-0 mt-0.5">${ic('github', 'w-4 h-4')}</span>
          <span><span class="text-sm font-medium group-hover:text-accent transition break-all">${r}</span>
          <span class="block text-xs text-muted mt-0.5">${role}</span></span>
        </a>`).join('')}
      </div>
    `)}
  </div>`;

  const final = `
  <div class="border-t border-border">
    <div class="mx-auto max-w-5xl px-6 py-20 text-center">
      <h2 class="text-3xl sm:text-4xl font-bold tracking-tight">Try it in five minutes</h2>
      <p class="mt-3 text-muted">Free, open source, and everything stays on your machine.</p>
      <div class="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
        ${cta()}
        <a href="#/download" class="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-border bg-surface text-sm font-semibold hover:border-accent/60 transition">Setup guide</a>
      </div>
    </div>
  </div>`;

  return hero + demo + different + features + how + perf + faq + ethics + credits + final;
}

/* ── DOWNLOAD ───────────────────────────────────────────────────────────── */
function pageDownload() {
  const d = Release.data || CONFIG.fallback;
  return `
  <div class="mx-auto max-w-3xl px-6 py-16 sm:py-24">
    <h1 class="text-4xl sm:text-5xl font-extrabold tracking-tight">Download</h1>
    <p class="mt-3 text-muted">Free and open source. No account, no telemetry. Released <span data-date>${d.date}</span>.</p>

    <div class="mt-10 rounded-2xl border border-accent/40 bg-surface overflow-hidden">
      <div class="p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-5">
        <div>
          <div class="text-xs uppercase tracking-wider text-muted font-semibold">Latest stable</div>
          <div class="mt-1 mono text-3xl font-bold" data-version>v${d.version}</div>
          <div class="mt-1 text-xs text-muted">Windows 10/11 64-bit · <span data-size>${d.sizeMB} MB</span></div>
        </div>
        <a data-link href="${d.url}" class="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-accent text-bg font-bold text-sm hover:bg-accent/90 transition">
          ${ic('download', 'w-4 h-4')} Download installer
        </a>
      </div>
      <div class="px-6 py-5 border-t border-border bg-surface2/40">
        <div class="text-[11px] font-bold uppercase tracking-wider text-muted">SHA-256</div>
        <div class="mt-2 flex items-center gap-2">
          <code data-sha class="mono text-xs bg-bg/60 border border-border rounded-lg px-3 py-2.5 break-all flex-1">${d.sha256 || 'See the release notes on GitHub'}</code>
          <button onclick="navigator.clipboard.writeText(document.querySelector('[data-sha]').textContent.trim());this.innerHTML='${ic('check', 'w-4 h-4').replace(/'/g, "\\'")}'"
                  class="shrink-0 p-2.5 rounded-lg border border-border text-muted hover:text-accent hover:border-accent/60 transition" aria-label="Copy hash">${ic('copy', 'w-4 h-4')}</button>
        </div>
        <p class="mt-2.5 text-xs text-muted leading-relaxed">Check it with <code class="mono bg-bg/60 px-1.5 py-0.5 rounded">certutil -hashfile VoxMorph-Setup.exe SHA256</code>. The built-in updater verifies this same hash before it will run an installer.</p>
      </div>
    </div>

    <div class="mt-5 rounded-2xl border border-warn/40 bg-warn/[0.04] p-5 flex gap-3.5 text-sm leading-relaxed">
      <span class="text-warn shrink-0 mt-0.5">${ic('alert', 'w-5 h-5')}</span>
      <div><strong>You also need a virtual audio cable.</strong>
      <span class="text-muted">Without one, other apps cannot hear the converted voice. Install the free
      <a class="text-accent hover:underline" href="https://vb-audio.com/Cable/" target="_blank" rel="noopener">VB-CABLE</a>, then reboot.</span></div>
    </div>

    <h2 class="mt-14 text-xl font-bold">After installing</h2>
    <ol class="mt-5 space-y-4">
      ${[['Open the Audio tab', 'Set Microphone to your real mic and Output to “CABLE Input”.'],
         ['Point your app at the cable', 'Discord → Settings → Voice &amp; Video → Input Device → “CABLE Output”. Turn Krisp off.'],
         ['Pick a voice and press Start', 'Wear headphones — speakers will feed your converted voice back into the mic.']]
        .map(([t, s], i) => `<li class="flex gap-4">
          <span class="shrink-0 w-7 h-7 rounded-lg bg-surface2 border border-border grid place-items-center mono text-xs font-bold text-accent">${i + 1}</span>
          <div><div class="font-semibold text-sm">${t}</div><div class="mt-1 text-sm text-muted leading-relaxed">${s}</div></div></li>`).join('')}
    </ol>

    <h2 class="mt-14 text-xl font-bold">Or build from source</h2>
    <pre class="mt-4 mono text-xs bg-surface border border-border rounded-2xl p-5 overflow-x-auto leading-relaxed">git clone https://github.com/${CONFIG.owner}/${CONFIG.repo}
cd ${CONFIG.repo}
python -m venv .venv &amp;&amp; .venv\\Scripts\\activate
pip install -r requirements.txt
python run.py</pre>
    <p class="mt-2.5 text-xs text-muted">Add <code class="mono">requirements-gpu.txt</code> and a CUDA build of PyTorch for neural identity voices.</p>

    <h2 class="mt-14 text-xl font-bold">Changelog</h2>
    <div id="changelog" class="mt-4"><div class="skeleton h-24 rounded-2xl"></div></div>
  </div>`;
}

/* ── DOCS ───────────────────────────────────────────────────────────────── */
const DOCS = [
  ['Getting started', [
    ['Install', 'Run the installer, add VB-CABLE, reboot. VoxMorph detects the cable and selects it automatically.'],
    ['Your first voice', 'Character presets work immediately. Identity voices need a model file — download one or import your own .pth.'],
  ]],
  ['Audio routing', [
    ['The cable', 'VoxMorph writes to CABLE Input; other apps listen on CABLE Output. Without a cable nothing else can hear you.'],
    ['Discord', 'Settings → Voice & Video → Input Device → CABLE Output. Disable Krisp and echo cancellation.'],
    ['OBS', 'Add an Audio Input Capture source and select CABLE Output.'],
  ]],
  ['Voices', [
    ['Identity vs character', 'Identity voices are speaker-locked — the same person out regardless of who speaks. Character presets transform your own voice and need no model.'],
    ['Importing models', 'Drop a .pth (and matching .index) into %LOCALAPPDATA%\\VoxMorph\\models, then press Refresh.'],
    ['Tuning for realism', 'Leave auto pitch match on, keep timbre strength between 0.5 and 0.75, and consonant protect near 0.33.'],
  ]],
  ['Latency', [
    ['Choosing a profile', 'Start on Low. Watch RT Load in the HUD: under 50% is comfortable, over 80% will drop out.'],
    ['If you hear crackling', 'Move to a slower profile, disable reverb and echo, switch the pitch engine from rmvpe to fcpe, or enable WASAPI exclusive mode.'],
  ]],
  ['Hotkeys', [
    ['Defaults', 'Ctrl+Alt+B bypass · Ctrl+Alt+M mute · Ctrl+Alt+←/→ cycle voices · Ctrl+Alt+P panic stop.'],
    ['Push to talk', 'Bind any key. Some anti-cheat drivers block keyboard hooks — run as administrator if hotkeys do nothing.'],
  ]],
  ['Command line', [
    ['Commands', 'voxmorph devices · voices · run --preset X · convert in.wav out.wav --preset X · check-update · doctor'],
    ['doctor', 'Checks every dependency, lists your audio devices, reports whether CUDA was found, and names anything missing.'],
  ]],
];

function pageDocs() {
  return `
  <div class="mx-auto max-w-5xl px-6 py-16">
    <h1 class="text-4xl font-extrabold tracking-tight">Documentation</h1>
    <div class="mt-10 grid md:grid-cols-[190px_1fr] gap-10">
      <nav class="md:sticky md:top-20 self-start" aria-label="Sections">
        ${DOCS.map(([t], i) => `<a href="#d${i}" class="block px-3 py-2 rounded-lg text-sm text-muted hover:text-ink hover:bg-surface transition">${t}</a>`).join('')}
      </nav>
      <div class="space-y-12 min-w-0">
        ${DOCS.map(([title, secs], i) => `
        <div id="d${i}">
          <h2 class="text-lg font-bold pb-2.5 border-b border-border">${title}</h2>
          <div class="mt-5 space-y-5">
            ${secs.map(([h, b]) => `<div>
              <h3 class="text-sm font-semibold text-accent">${h}</h3>
              <p class="mt-1.5 text-sm text-muted leading-relaxed">${b}</p></div>`).join('')}
          </div>
        </div>`).join('')}
      </div>
    </div>
  </div>`;
}

/* ── SHELL + ROUTER ─────────────────────────────────────────────────────── */
function shell(content) {
  const nav = [['#/', 'Home'], ['#/download', 'Download'], ['#/docs', 'Docs']];
  const here = location.hash || '#/';
  return `
  <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:px-4 focus:py-2 focus:rounded-lg focus:bg-accent focus:text-bg focus:font-semibold">Skip to content</a>
  <header class="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-md">
    <div class="mx-auto max-w-5xl px-6 h-14 flex items-center justify-between">
      <a href="#/" class="flex items-center gap-2.5 font-bold tracking-tight">
        <span class="w-6 h-6 rounded-lg bg-accent/12 border border-accent/30 grid place-items-center text-accent">${ic('audio-waveform', 'w-3.5 h-3.5')}</span>
        VoxMorph
      </a>
      <nav class="flex items-center gap-0.5 text-sm">
        ${nav.map(([h, l]) => `<a href="${h}" class="px-3 py-1.5 rounded-lg transition ${here === h || (h !== '#/' && here.startsWith(h)) ? 'text-ink font-medium' : 'text-muted hover:text-ink'}">${l}</a>`).join('')}
        <a href="https://github.com/${CONFIG.owner}/${CONFIG.repo}" target="_blank" rel="noopener"
           class="ml-1 p-2 rounded-lg text-muted hover:text-ink transition" aria-label="GitHub">${ic('github', 'w-4 h-4')}</a>
      </nav>
    </div>
  </header>
  <main id="main">${content}</main>
  <footer class="border-t border-border bg-surface/30">
    <div class="mx-auto max-w-5xl px-6 py-12 grid grid-cols-2 sm:grid-cols-4 gap-8 text-sm">
      <div><div class="font-semibold mb-3">Product</div>
        <a href="#/download" class="block text-muted hover:text-ink py-1 transition">Download</a>
        <a href="#/docs" class="block text-muted hover:text-ink py-1 transition">Documentation</a></div>
      <div><div class="font-semibold mb-3">Source</div>
        <a href="https://github.com/${CONFIG.owner}/${CONFIG.repo}" target="_blank" rel="noopener" class="block text-muted hover:text-ink py-1 transition">GitHub</a>
        <a href="https://github.com/${CONFIG.owner}/${CONFIG.repo}/issues" target="_blank" rel="noopener" class="block text-muted hover:text-ink py-1 transition">Report a bug</a></div>
      <div><div class="font-semibold mb-3">Legal</div>
        <a href="https://github.com/${CONFIG.owner}/${CONFIG.repo}/blob/main/LICENSE" target="_blank" rel="noopener" class="block text-muted hover:text-ink py-1 transition">MIT License</a>
        <span class="block text-muted py-1">Nothing collected</span></div>
      <div class="text-xs text-muted leading-relaxed">
        <div class="flex items-center gap-1.5 font-semibold text-ink mb-2.5">${ic('shield', 'w-3.5 h-3.5')} Private by default</div>
        No analytics, no account. Your audio never leaves the machine.</div>
    </div>
    <div class="border-t border-border py-5 text-center text-xs text-muted">VoxMorph — MIT licensed.</div>
  </footer>`;
}

function paintChangelog() {
  const el = document.getElementById('changelog'); if (!el) return;
  const d = Release.data;
  if (!d || !d.live) {
    el.innerHTML = `<div class="rounded-2xl border border-border bg-surface p-5 text-sm text-muted">
      Release history loads from GitHub once the repository is published.
      <a class="text-accent hover:underline" href="https://github.com/${CONFIG.owner}/${CONFIG.repo}/releases" target="_blank" rel="noopener">View releases →</a></div>`;
    return;
  }
  const lines = d.notes.split('\n')
    .filter(l => l.trim() && !/^[a-f0-9]{64}$/i.test(l.trim()) && !/sha256/i.test(l))
    .slice(0, 12);
  el.innerHTML = `<div class="rounded-2xl border border-border bg-surface p-5">
    <div class="flex items-center gap-2 text-sm font-bold">${ic('refresh-cw', 'w-4 h-4 text-accent')} v${d.version}
      <span class="font-normal text-xs text-muted">${d.date}</span></div>
    <div class="mt-3 space-y-1 text-sm text-muted">${lines.map(l => `<div>${l.replace(/^[-*#>\s]+/, '')}</div>`).join('')}</div>
  </div>`;
}

function route() {
  Player.stop();
  const h = location.hash || '#/';
  const view = h.startsWith('#/download') ? pageDownload() : h.startsWith('#/docs') ? pageDocs() : pageHome();
  document.getElementById('app').innerHTML = shell(view);
  if (!h.includes('#d')) window.scrollTo(0, 0);
  paintRelease();
  paintChangelog();
  heroWave();
}

window.Player = Player;
addEventListener('hashchange', route);
route();
fetchRelease();
