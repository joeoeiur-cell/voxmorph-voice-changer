# Website build prompt

Copy everything inside the block below into an AI website builder (v0, Lovable, Bolt, Claude, Cursor…). It is written to be pasted verbatim.

---

```
Build a production-ready marketing and download website for "VoxMorph", a realtime
AI voice changer for Windows.

=========================
1. PRODUCT CONTEXT
=========================
VoxMorph is a desktop app (Windows .exe) that changes your voice in realtime for
Discord, OBS, games and streaming.

Its core differentiator, which the site must communicate clearly and early:
most voice changers just shift pitch, so you still sound like yourself. VoxMorph
has PRESET IDENTITY VOICES powered by RVC neural models — a trained decoder
replaces your timbre entirely, so the output sounds like the SAME target person
no matter who speaks into the microphone. It also has instant DSP character
presets that need no GPU and no download.

Key specs to use as real copy (do not invent different numbers):
- Latency: 40-150 ms end to end; four profiles (Ultra-Low ~55 ms, Low ~90 ms,
  Balanced ~150 ms, Max Quality ~250 ms)
- DSP rack measured at ~8 ms p95 against a 60 ms block budget
- 15 built-in character presets + unlimited importable RVC identity voices
- Pitch accuracy: YIN tracker accurate to under one cent
- Works on CPU (character voices) or GPU (identity voices, CUDA/DirectML)
- Free and open source, MIT licensed
- Auto-updating with SHA-256 verified installers

=========================
2. TECH STACK
=========================
- Next.js 14 (App Router) + TypeScript
- Tailwind CSS
- Framer Motion for scroll and hover animation
- shadcn/ui components
- next-themes for dark/light (DEFAULT TO DARK)
- Fully responsive: 375 px mobile -> 1920 px desktop
- Static export capable so it can deploy to Vercel, Netlify or GitHub Pages

=========================
3. VISUAL DESIGN
=========================
Dark, technical, audio-software aesthetic. Think a professional DAW plugin, not
a generic SaaS landing page. NO purple gradients, NO rainbow AI clichés.

Palette (use exactly):
  background   #0e1116
  surface      #161b22
  surface-alt  #1c2330
  border       #2a3441
  text         #e6edf3
  text-muted   #8b98a5
  accent       #22d3ee   (cyan - use sparingly, for CTAs and active states)
  accent-dark  #0e7490
  success      #34d399
  warning      #fbbf24

Type: Inter or Geist for UI; JetBrains Mono for numbers, specs and code.
Style: 8-12 px border radii, 1 px #2a3441 borders, generous whitespace,
subtle depth from borders and layered surfaces rather than heavy drop shadows.
A faint animated waveform or spectrum motif may appear in the hero, but keep it
restrained and make it respect prefers-reduced-motion.

=========================
4. PAGES AND SECTIONS
=========================

--- HOME (/) ---

HERO
  H1: "Sound like someone else. Not like yourself, higher."
  Sub: "Realtime AI voice changer with speaker-locked preset voices.
        Sub-100 ms latency. Free and open source."
  Primary CTA:   "Download for Windows"  (large, cyan, shows version + file size)
  Secondary CTA: "View on GitHub"        (ghost button with star count)
  Under the buttons, small muted text: "Windows 10/11 64-bit · ~180 MB · MIT licensed"
  Right side / background: an animated realtime spectrum analyser built in
  canvas, plus a floating screenshot of the app UI in a dark rounded frame.

THE DIFFERENTIATOR (place immediately after hero - this is the most important section)
  Heading: "Preset voices, not pitch sliders"
  A two-column comparison card:
    LEFT  "Ordinary voice changers"  - pitch shifting - you still sound like you
          - different for every speaker - obvious artefacts
    RIGHT "VoxMorph identity voices" - neural timbre replacement
          - the SAME voice for every speaker - trained decoder, not a filter
  Below, a short technical explainer in plain language:
    "RVC splits speech into content (what you say) and identity (who you sound
     like). Your mic only supplies the content and pitch contour. The model
     always renders it in the target speaker's voice."
  Include an interactive A/B audio player component: a row of sample voices,
  each with an "Original" and "Converted" toggle, waveform scrubber, and a
  visible latency badge. Use placeholder audio files at /audio/*.mp3 and make
  the component read from a typed config array so samples are easy to swap.

FEATURES GRID
  Responsive grid, 1 col mobile / 2 tablet / 3 desktop. Each card has a
  lucide-react icon, title, one-line description. Cover:
    - Identity preset voices (speaker-locked)
    - 15 instant character presets (no GPU, no download)
    - Zero-shot cloning from a 15-second clip
    - Sub-100 ms realtime latency
    - Studio effects rack: denoise, gate, compressor, de-esser, EQ, limiter
    - Reverb, echo, chorus, robot, telephone, megaphone, monster, alien
    - Global hotkeys: push-to-talk, mute, bypass, panic stop
    - Soundboard with polyphonic playback
    - Dual-track recording (original + converted)
    - Auto pitch matching to the target voice
    - Live VU meters, spectrum and latency HUD
    - Automatic SHA-256 verified updates

HOW IT WORKS
  Four numbered steps with connecting line:
    1. Install VoxMorph and VB-CABLE (free virtual audio cable)
    2. Pick a voice from the library
    3. Set your app's microphone to "CABLE Output"
    4. Talk - you are heard as the target voice
  Include a small routing diagram: Mic -> VoxMorph -> Virtual Cable -> Discord/OBS/Game

PERFORMANCE
  Dark technical panel with three big monospace stat blocks:
    "40-150 ms"  end-to-end latency
    "~8 ms"      DSP processing per 60 ms block (p95)
    "<1 cent"    pitch tracking accuracy
  Beside it, the latency-profile table (Ultra-Low / Low / Balanced / Max Quality)
  and a short note that neural inference runs off the audio callbacks so a slow
  block causes a buffer dip, not a dropout.

VOICE LIBRARY PREVIEW
  Horizontally scrollable cards of the built-in presets (Deep Male, Radio Host,
  Young Female, Kid, Giant, Demon, Alien, Ghost, Robot, Telephone, Megaphone,
  Old Man, Chipmunk, Soft Female, Natural). Each card shows the name, category
  badge, a one-line description and a play button. Tag identity voices with a
  cyan "IDENTITY" pill and character voices with a muted "CHARACTER" pill.

SYSTEM REQUIREMENTS
  Two columns, Minimum vs Recommended:
    Minimum:     Windows 10 64-bit, 4-core CPU, 4 GB RAM, 500 MB disk
                 (character presets, ~2 ms latency)
    Recommended: Windows 11, NVIDIA RTX 2060+ (6 GB VRAM), 16 GB RAM, 3 GB disk
                 (identity voices at 40-90 ms)

OPEN SOURCE
  Credit the projects VoxMorph builds on, each as a linked card:
  RVC-Project/Retrieval-based-Voice-Conversion-WebUI, daswer123/rvc-python,
  deiteris/voice-changer, Plachtaa/seed-vc, IAHispano/Applio.
  Add a GitHub star CTA.

FAQ (accordion)
  - Is it really free? (Yes, MIT licensed, no account, no telemetry)
  - Do I need a GPU? (No for character voices, yes recommended for identity voices)
  - Why do I need a virtual audio cable?
  - Does it work with Discord / OBS / Valorant / Zoom?
  - How much latency will I actually get?
  - Can I add my own voice models? (Yes - drop any .pth in the models folder)
  - Can I clone someone's voice? (Only with their consent - see ethics)
  - Is my audio sent anywhere? (No - 100% local processing, no network audio)

ETHICS BANNER
  A distinct bordered callout, warning colour, not hidden in the footer:
  "Use responsibly. Only clone voices you have permission to use. Impersonation
   for fraud, harassment or bypassing voice authentication is illegal in many
   jurisdictions. VoxMorph ships no third-party voice models."

FINAL CTA + FOOTER
  Footer columns: Product (Download, Features, Changelog), Resources (Docs,
  GitHub, Report a bug), Legal (License, Privacy, Ethics). Note "No tracking,
  no analytics, no account required."

--- DOWNLOAD (/download) ---
  - Big primary Windows download card: version, file size, release date, SHA-256
    in a monospace copy-to-clipboard field
  - Instruct users to verify with:  certutil -hashfile VoxMorph-Setup.exe SHA256
  - Secondary: "Build from source" card with the git clone + pip commands
  - A required "You will also need VB-CABLE" card linking to vb-audio.com/Cable/
  - Post-install quick-start: the four routing steps again, with screenshots
  - Changelog section rendered from the GitHub Releases API

--- DOCS (/docs) ---
  Sidebar-navigated docs with pages: Getting Started, Audio Routing, Voice
  Library, Importing RVC Models, Effects Rack, Hotkeys, Latency Tuning,
  Troubleshooting, CLI Reference. Use MDX. Include a working search box.

=========================
5. LIVE GITHUB INTEGRATION
=========================
Create a typed helper lib/github.ts that fetches from the GitHub Releases API:
    https://api.github.com/repos/<OWNER>/voxmorph/releases/latest
Use it to populate, with ISR revalidation every 3600 seconds:
  - the version number on every download button
  - installer file size (from the asset, formatted MB)
  - release date
  - SHA-256 (parse the 64-hex-char string out of the release body)
  - the changelog list
Handle the API failing gracefully: fall back to hardcoded values from a
config file, never render "undefined" or a broken button. Put OWNER/REPO in
a single config constant at the top so it is trivial to change.

=========================
6. QUALITY REQUIREMENTS
=========================
- Semantic HTML5, correct heading hierarchy, WCAG AA contrast
- Full keyboard navigation, visible focus rings, aria labels on all icon buttons
- Respect prefers-reduced-motion for every animation
- next/image for all images, lazy loading below the fold
- Complete SEO: title/description per page, Open Graph + Twitter card images,
  JSON-LD SoftwareApplication schema (name, OS, price 0, license, rating slot),
  sitemap.xml and robots.txt
- Lighthouse target 95+ on all four categories
- No layout shift on load; reserve space for async GitHub data with skeletons
- Zero client-side tracking or analytics scripts

=========================
7. DELIVERABLES
=========================
Full project source with:
  - app/ routes for /, /download, /docs
  - components/ with the AudioComparePlayer, SpectrumHero, FeatureGrid,
    VoiceCard, LatencyTable, FAQAccordion, DownloadCard, EthicsBanner
  - lib/github.ts, lib/config.ts (all product constants in one place)
  - Tailwind config with the exact palette above as named colours
  - A README explaining how to run, configure OWNER/REPO, and deploy
  - Placeholder assets in /public so the site renders with nothing missing
```

---

## Notes for whoever runs this prompt

- Replace `<OWNER>` with your GitHub username before pasting, or fix it afterwards in `lib/config.ts`.
- The audio A/B player is the single highest-converting element on a page like this. Record real before/after samples as soon as you have a voice model you are allowed to distribute.
- The SHA-256 shown on the download page is the same hash the app's updater verifies, so it comes straight from the release body your CI writes.
