# Noise-bed glitch engine — implementable spec (verified against `programmed-music`)

Scope: pure-Python stdlib-only real-time mixer, 48 kHz s16le stereo → ffplay pipe.
Everything below is either (a) quoted from the project, or (b) transcribed from the
SuperDough/Strudel source that project actually runs on, or (c) standard DSP math.

---

## 0. Ground truth about the project (read this first — it changes the plan)

I read the whole repo (excluding `.npm-cache`, `node_modules`, `.git`). Four facts
that matter more than any individual line:

**0.1 — `scripts/audio_lib.mjs` is not a DSP file at all.** It is 96 lines of file
probing: `duration()` shells out to `ffprobe`, `wavHeader()` parses a RIFF header by
hand, `scanAudio()` walks the workspace for `.wav/.flac/.mp3/.ogg/.m4a`, `findAudio()`
matches a score to a same-named WAV, `toCycles()` converts seconds ↔ cycles. The only
DSP-adjacent thing in it is the WAV byte-rate math:

```js
const byteRate = fmt.rate * fmt.ch * (fmt.bits / 8)   // scripts/audio_lib.mjs:35
return dataBytes > 0 ? dataBytes / byteRate : null
```
There is **no synthesis code anywhere in the repo**. Do not look for it.

**0.2 — the project is zero-randomness by explicit policy.** `rending.strudel:9`,
`shattered_mirror.strudel:4`, `storm_walk.strudel:10`, and `docs/mini-syntax.md:28` all
state it. `docs/COMPOSITION.md:69` mentions `sometimes` exactly once — as a *rejected*
suggestion. So the project is **not** a source of glitch-by-random-mutation technique.

**0.3 — noise appears in the project exactly twice, once as data and once as a word.**
Full grep over all `.strudel` for `white|pink|brown|crackle|sizzle|noise`:
- `patterns/visual_lab.strudel:46` → `.color("white")` — a *colour*, not a sound.
- `patterns/visual_lab.strudel:75` → a *comment* mentioning `_scope({ color: 'white' })`.
- `patterns/pan_rain/a_full.strudel:36` → `white@48 ~@204` — **the one real noise line**.
- `patterns/pan_rain/chorus_voice.strudel:245` → `gm_breath_noise@3` — a GM *sample*.
That's it. There is no `s("pink")`, no `s("brown")`, no `crackle`, no `sizzle` in any pattern.

**0.4 — the project's noise/synth vocabulary comes from `docs/sounds/synths.md`**, a
3-line dump of Strudel's built-in synth names. Non-GM entries (extracted in full):
`brown bytebeat crackle one pink pulse saw sawtooth sbd sin sine sqr square supersaw tri
triangle user white z_noise z_sawtooth z_sine z_square z_tan z_triangle zzfx`.
`docs/sounds/samples.md` and `docs/sounds/drum-machines.md` are the same kind of dump
(sample and drum-machine names). `docs/sounds/wavetables,.md` has 7 entries
(`wt_digital*`, `wt_vgame`).

**0.5 — the `addEffect` set of `crush/coarse/shape/distort/vowel/phaser/compressor/
postgain/room/delay/orbit` is NOT used by any pattern.** grep across the whole repo for
those tokens returns only: `.shape(0.15)` ×3 in `rending.strudel:129,135,148`,
`.shape(.18)` in `homeward_demo.strudel:373`, `.postgain()` in `reference/`, and
`.vib(sine.range(.18, .3).fast(1))` in `pan_rain/a_full.strudel:328` +
`chorus_full.strudel:262`. **Zero** uses of `crush`, `coarse`, `vowel`, `phaser`,
`compressor`, `duck`, `hpf`, `bpf`, `biquad` anywhere in `patterns/`.

⇒ **Conclusion:** the project gives you *one* noise idiom and a large amount of
discipline about *how to evolve a parameter without randomness*. For the actual
synthesis recipes you asked for, I went to the source the project's docs index:
**SuperDough 1.2.6** (the version `package.json` pins: `@strudel/tonal ^1.2.6`; installed
`node_modules/@strudel/core` is **1.2.6**). Section 2 quotes its real algorithms where
they exist, so your Python matches what strudel.cc would play.

---

## 1. What the project actually does, grouped, with exact lines

### 1.1 Noise proper — one line, and it is the whole idiom

`patterns/pan_rain/a_full.strudel:35-42` (the "白噪 solo" intro, 48 units of 35.00 s):

```js
const nz = sound(`
white@48 ~@204
`)
  .velocity(`
1@48 ~@204
`)
  .gain(.07).attack(.9).decay(3).sustain(.9).release(2.4)
  .lpf(sine.range(300, 3400).fast(1)).room(.92).pan(sine.range(.35, .65).fast(1))
```

Sonic content, exactly:
- `s("white")` = uniform white noise, −1..+1 per sample (see §2.1 for the source).
- `.gain(.07)` → the bed sits **23 dB below full scale**, i.e. ≈ −30 dBFS peak.
- **full ADSR on noise** (`.attack(.9).decay(3).sustain(.9).release(2.4)`): a 0.9 s
  fade-in, 3 s decay to 90 % of peak, held, 2.4 s tail. That is what turns "static"
  into "air entering a room".
- `.lpf(300 → 3400 Hz, one full cycle of a sine LFO)` — a **slow, continuous** sweep.
  `sine.range(a,b).fast(1)` is the project's canonical LFO: exactly one ramp per cycle,
  chosen because intra-cycle segmented control splits sustained notes
  (`docs/mini-syntax.md:66-71`).
- `.room(.92)` — near-maximum reverb send, so the noise is mostly *room*, not source.
- `.pan(.35 → .65)` — slow stereo drift under a sine, ±0.15 around centre.

This single line is your template for the bed: **slow LFO on filter + big reverb +
slow pan**. Everything else in §3 is built on it.

Sample-based noise/ambience in the same project, for the textures that are not synth noise:
- `pan_rain/a_full.strudel:373-376` — `const amb = sound(\`~@60 oceandrum@96 ~@8 wind@88\`)`
  with `.gain(.03).release(3).legato(1).room(.95).pan(sine.range(.25, .75).fast(1))`.
  `oceandrum` and `wind` are sample-library names (see `docs/sounds/samples.md`:
  `oceandrum(3)`, `wind(10)`). This is the "room floor" under the whole A-section.
- `pan_rain/chorus_voice.strudel:245` — `gm_breath_noise@3` at `.gain(.05)`,
  `.attack(.01).decay(.3).sustain(.2).release(.12)` — a *sampled* inhale used as a
  punctuation mark inside a 4-unit gap.

### 1.2 Filters — only `lpf`, always a control, never a one-shot

The project uses **only low-pass**, and never `hpf`/`bpf`/`biquad`/`cutoff`-as-filter
(the `cutoff(280)` calls in `odd_hour.strudel:281,292,297,316,327,332` are a *different,
older* control name; `lpf` is the one `docs/mini-syntax.md:86` lists as verified).
Two distinct idioms:

**(a) Stepped low-pass as a build-up device** — a fixed sequence under `<>`, one value
per cycle. `shattered_mirror.strudel:105`:
```js
[8, leadBuild1.lpf("<500 600 750 950 1200 1500 0 0>").gain("<0 .16 .18 .20 .22 .24 0 0>")],
```
`shattered_mirror.strudel:229` (strings), `rending.strudel:122,128,134,141,147,152`,
`rending.strudel:280`, `rending.strudel:455,464,473` (the trance-gate layer:
`.lpf("[800 1000 1200 1400]")` — square-bracket = sub-cycle, so per-**beat**).
Note the `0` at the end of several sequences: `lpf(0)` is *fully closed*, used as the
project's way of writing silence-through-filter.

**(b) Continuous sine sweep** — `sine.range(a, b).slow(n)`/`.fast(1)`, for motion that
must not chop notes:
- `shattered_mirror.strudel:230` — `.lpf(sine.range(900, 1800).slow(8))` (strings, 8 cycles/ramp)
- `shattered_mirror.strudel:271` — `.lpf(sine.range(280, 950).slow(4))` (bass)
- `rending.strudel:296` — `.lpf(sine.range(700, 1400).slow(8))`
- `rending.strudel:304` — `.lpf(sine.range(1000, 2200).slow(24))` (24-cycle ramp = 34 s)
- `homeward_demo.strudel:279` — a 28-value stepped string, 1100 Hz up to 2400 Hz and back
- `homeward_demo.strudel:556` — `.lpf(sine.range(1200, 14000).slow(3))` on the drums bus
- `storm_walk.strudel:207,219,232` — pad layers swept 500→1100, 900→1600, 1000→2000 Hz
- `pan_rain/a_full.strudel:42` — the 300→3400 Hz bed sweep quoted above
- `pan_rain/a_full.strudel:265` — `.lpf(sine.range(720, 980).fast(1))`

**Range summary you can steal directly:** musical sweeps live in **200–3400 Hz**;
"opening up" caps around **2200–2800 Hz**; drum-bus sweeps go to **14 kHz**.

### 1.3 Envelopes — full `attack/decay/sustain/release`, times in seconds

The four-control form is used 30+ times, almost always on the pad/ambient layers:

| file:line | line | intent |
| --- | --- | --- |
| `pan_rain/a_full.strudel:41` | `.attack(.9).decay(3).sustain(.9).release(2.4)` | white-noise bed breathing in |
| `pan_rain/a_full.strudel:306` | `.attack(2.2).decay(3).sustain(.6).release(3.6)` | 2.2 s swell, huge tail (the "光"/glow layer) |
| `pan_rain/a_full.strudel:131,143` | `.attack(.006).decay(1.2).sustain(.55).release(3)` | mallet with a long ring |
| `pan_rain/a_full.strudel:275,285,295` | `.attack(.006).decay(.3).sustain(.9).release(.12)` | palm-stop stab: **release .12 s = "手掌按停"** |
| `pan_rain/chorus_full.strudel:240` | `.attack(3.2).decay(4).sustain(.7).release(4.2)` | the longest swell in the repo |
| `pan_rain/full_arrangement.strudel:81` | `.attack(.008).decay(1.8).sustain(.62).release(4.5)` | |
| `pan_rain/full_arrangement.strudel:200,362` | `.attack(.006).decay(1.6).sustain(.5).release(3)` / `.decay(1.2).sustain(.55).release(3.2)` | |
| `pan_rain/dance_strings.strudel:71,113,155` | `.attack(.05).decay(.8).sustain(.6).release(1.2)` etc. | bowed strings |
| `pan_rain/mini_full.strudel:94,151` | `.attack(.006).decay(1.2).sustain(.5).release(2.4)` / `.decay(1.4)...release(3.2)` | |

Two-control shorthand is the norm for everything else:
`.attack(.004).release(.25)` (piano, `visual_lab.strudel:31`),
`.attack(.003).release(.08)` (bass, `rending.strudel:170`),
`.attack(.003).release(.16)` (piano, `storm_walk.strudel:177`),
`.attack(.55).release(2.2)` (pad, `storm_walk.strudel:219`),
`.attack(.02).release(3)` + `.room(0.8)` (**the fake-stop piano**:
`rending.strudel:418`, `shattered_mirror.strudel:343` — identical construction in both).

**Critical for you:** `release` is where all the "texture" lives. `docs/mini-syntax.md:73-77`
records the empirical rule the project settled on: *"want things to stick together, the
only two guarantees are **give `release` long** and **overlap the voices***"* — `legato()`
is invisible on the Node side and cannot be relied on.

**Exact SuperDough semantics of the four controls** (`superdough/helpers.mjs`,
`getADSRValues` + `getParamADSR`) — implement this, not a textbook ADSR:

```js
// defaults when NOTHING is set:  [0.001, 0.001, 1, 0.01]   (a gate, not an envelope)
// sustain default:
//   if attack set and decay NOT set  -> sustain = 1
//   if neither attack nor decay set  -> sustain = 1
//   if decay set but attack not      -> sustain = 0.001
// a = max(a, 0.001), d = max(d, 0.001), r = max(r, 0.01)
```
Then, over the note's held time `[begin, begin+duration]`:
```
if attack > duration:            ramp min -> envVal(duration)                      at end
elif attack + decay > duration:  ramp min -> peak at begin+attack, then -> envVal(duration) at end
else:                            ramp min -> peak at begin+attack
                                 ramp peak -> sustainVal at begin+attack+decay
                                 set sustainVal at end
always:                          ramp min at end+release
```
where `envVal(t) = t * slope(min→peak over [0,attack])` for `t < attack`, else
`(t-attack) * slope(peak→sustainVal over [0,decay]) + peak`. Curve is **`'linear'`
for amplitude** and **`'exponential'` for filter cutoff / pitch** (SuperDough passes
`'linear'` in `registerSynthSounds`, `'exponential'` in `createFilter`). Exponential
ramps clamp the floor to 0.001.

### 1.4 `shape` — the only waveshaper the project uses

`rending.strudel:129,135,148` (Reese bass, all three drops) and
`homeward_demo.strudel:373`:
```js
  .shape(0.15)
  ...
  bassCore.s("sawtooth").lpf(sine.range(500, 1600).slow(2)).shape(.18)
```
`docs/mini-syntax.md:89` documents it as *"the bigger x, the more the mids bite"*.
That is accurate. **Exact SuperDough formula** (`superdough/worklets.mjs`,
`ShapeProcessor`) — this is a *soft saturator*, not a clipper:

```
shape' = min(shape, 1 - 4e-10)
k      = 2*shape' / (1 - shape')
y      = ((1 + k) * x) / (1 + k * |x|) * postgain      # postgain = shapevol, default 1
```
At `shape = 0.15` → `k = 0.3529`, so the curve is mild (`y ≈ 1.35x` for small `x`,
compressing to ±1). **That is why "cheap and flat" happens: the project never exceeds
`shape ≈ 0.18`.** For a horror demo you want `shape 0.6–0.95` (`k = 3 → 38`), or the
`distort` control below.

### 1.5 `crush` / `coarse` / `distort` / `vowel` / `phaser` / `compressor` / `duck` — used by NO pattern, but present in the engine

Available and verified by reading the installed engine's source (§2 has the math):

- **`crush`** — bit-depth quantiser. `superdough/worklets.mjs` `CrushProcessor`:
  `x = 2^(crush-1); out = round(in * x) / x`. `crush` = effective *bits*.
- **`coarse`** — sample-and-hold decimation. `CoarseProcessor`:
  `out[n] = (n % round(max(1,coarse)) == 0) ? in[n] : out[n-1]` — i.e.
  **hold each sample for `coarse` samples**; the sample rate becomes `48000/coarse`.
- **`distort` + `distorttype`** — 9 selectable waveshapers (`_scurve`, `_soft`, `_hard`,
  `_cubic`, `_diode`, `_asym`, `_fold`, `_sinefold`, `_chebyshev`), applied as
  `postgain * algo(x, expm1(distort))`. Default `distorttype = 0` = `_scurve`.
- **`vowel`** — 5 parallel band-passes at real formant frequencies, makeup gain 8.
  Full table in §2.7.
- **`phaser`** (= `phaserrate`), `phaserdepth` (default **0.75**), `phasersweep`,
  `phasercenter` — 2 notch biquads in series, `f = center + {0, 282} Hz`, Q = 2 − min(depth×2, 1.9).
  **Default phaserdepth is 0.75, not 0** — so `.phaser(x)` alone is audible.
- **`compressor`** + `compressorRatio/Knee/Attack/Release` → `DynamicsCompressorNode`
  with defaults `threshold −3 dB, ratio 10, knee 10, attack 0.005 s, release 0.05 s`.
- **`duckorbit` / `duckonset` / `duckattack` / `duckdepth`** → real sidechain ducking of
  another orbit at `t + duckonset`, ramping over `duckattack`.
- **`postgain`** (default 1) is applied *last*, after pan and phaser — the master trim
  of a single voice. `gain` vs `postgain`: `gain` is pre-FX, `postgain` is post-FX.
- **`ftype`**: `0 = '12db'` (one biquad), `1 = 'ladder'` (4-pole tanh ladder worklet,
  `drive` default 0.69), `2 = '24db'` (the biquad **twice** in series). Default `'12db'`.
- **`fanchor`** (default 0), **`resonance`** / `hresonance` / `bandq` (default **1.0**) —
  note `resonance = 1` is *not* "no resonance" in the Web Audio sense; the ladder
  clamps `k = min(8, Q * 0.13)`.

### 1.6 `room` / `delay` / `orbit` / `pan` — the actual spatial grammar

- `room` is a **send amount 0..1** into a per-orbit **convolution** reverb whose IR is
  generated at runtime (`superdough/reverb.mjs` → `reverbGen.generateReverb`), shaped by
  `roomsize` (decay time), `roomfade`, `roomlp` (start LP freq, default 15000),
  `roomdim` (end LP freq, default 1000 — **the reverb gets darker as it decays**; this is
  the single most valuable fact in this subsection for a horror demo).
- **The project uses exactly two room values as a hard rule.**
  `pan_rain/a_full.strudel:21-22`: *"room 只有两档（.45-.5 室内 / .8-.92 大厅）"* —
  **two settings only: .45–.5 = room, .8–.92 = hall**. Also `a_full.strudel:18,21`:
  *all `delaytime` = one beat = `delaytime(5/9)`* at 108 BPM, and all delay feedback
  comes from the default (`delayfeedback = 0.5`).
- Observed room values across the repo: `.12 .14 .15 .16 .18 .2 .22 .24 .25 .26 .28 .3
  .32 .34 .35 .38 .4 .42 .45 .5 .55 .6 .62 .65 .66 .7 .8 .82 .85 .9 .92 .95`
  (`.95` twice: `a_full.strudel:376`, `chorus_full.strudel:300` — the ocean-drum floor).
- `delay` = send amount; `delaytime` in seconds (or `delaysync` in cycles, default 3/16);
  `delayfeedback` default **0.5**. Delay only engages when all three are non-zero
  (`superdough.mjs`: `if (delay > 0 && delaytime > 0 && delayfeedback > 0)`).
- `orbit` = **bus index** (default 1); delay and reverb are created per orbit, so
  `orbit` is how you give different voices different spaces. `channels` default `[1,2]`.
- `pan`: `.pan(value)` maps to `StereoPanner.pan = 2*pan − 1`, so **0.5 = centre**,
  and `pan` is *not* clamped in code. Idioms: fixed (`.pan(.3)`, `.pan(.75)`),
  and drifting `sine.range(.35, .65).fast(1)` / `sine.range(.25, .75).fast(1)`.

### 1.7 `speed`, `n`, `unison`, `detune`, `fm`

- **`speed`** — used *only* as `speed(0)` semantics (sampler silence). No pattern in the
  repo uses `speed` as a creative playback-rate control. `docs/sounds/*.md` list no
  `speed` values.
- **`n`** — in the project, `n` means one of three things and `docs/mini-syntax.md:20,57-61`
  is emphatic that **`x:0.8` is NOT velocity**: `note("a4:.7")` yields `{note:'a4', n:0.7}`,
  i.e. **sample index**. Real uses: `n("0 2 4 7").fast(4).scale(...)` (scale degree,
  `rending.strudel:215,220,230,235`), `n("[0,2,4,7]").fast(4).scale(...)` (the trance-gate
  chord, `rending.strudel:451,460,469`), and `gm_epiano1:2` (sample variant,
  `homeward_demo.strudel:266`). Per-hit loudness is a **parallel `.velocity()` string with
  matching weights** — `pan_rain/a_full.strudel:38-40`, `:48-50`, `:71-76`.
- **`unison` / `detune`** — `unison` appears **nowhere** in `patterns/` (only `supersaw`'s
  internal `unison = 5, spread = 0.6`). `detune` is used a lot but **as a static cent
  offset**, not as a unison spread:
  `.detune(3)`, `.detune(-3)`, `.detune(4)`, `.detune(2)`, `.detune(-2)`, `.detune(6)`
  (`a_full.strudel:51,142,263,274,284,294` — pan-drum shimmer),
  `.detune(10)` (`chorus_voice.strudel:150`), and slow drift
  `.detune(sine.range(-10, 10).slow(2))` (`homeward_demo.strudel:66`),
  `.detune(sine.range(-14, 14).slow(1.5))` (`homeward_demo.strudel:104`),
  `.detune(sine.range(-4, 4).fast(1))` (`chorus_voice.strudel:58`),
  `.detune(0.22)` (`reference/bilibili/a_cybers_world.txt:162`).
  `docs/mini-syntax.md:88`: `detune(sine.range(±8,14).slow(n))` = *slow cent wobble, the
  "breath" of voice/brass, zero random*, and **never `.fast(n)` on a sustained layer**.
- **`fm`** (SuperDough: `fmh` harmonicity, `fmi` index, `fmwave`, `fmattack/decay/
  sustain/release`, `fmenv`): **zero uses in `patterns/`**. `fmfreq` also exists as a name.
  You do not need to imitate anything here.

### 1.8 `room`/`delay`/`chop`/`striate`/`slice`/`sometimes`/`degrade`/`sizzle`

Confirmed **absent from every `.strudel` in the repo**: `chop`, `striate`, `slice`,
`degrade`, `sometimes`, `sizzle`, `hpf`, `bpf`, `vowel`, `crush`, `coarse`, `compressor`,
`duck`, `postgain` (in `patterns/`), `orbit`, `phaser`, `unison`.
Notes for accuracy:
- `sometimes` is listed as verified-present on `Pattern.prototype` by
  `docs/strudel-lambda.md:293-295` (`when apply echo echoWith jux chunk ply arp iter
  filter someCycles firstOf outerJoin` and friends) — the project just refuses to use it.
- `degrade`, `chop`, `striate`, `slice`, `sizzle` I could **not verify against the
  installed package** (no `node_modules/superdough` here; only `core/mini/tonal/transpiler`
  are installed). Treat them as "strudel.cc may have them, this machine can't prove it".
- `sizzle` in particular appears in **your `docs/sounds/synths.md` dump but not in the
  SuperDough 1.2.6 noise registry** (§2.1): the registered noise synths are exactly
  `['pink','white','brown','crackle']`. So `s("sizzle")` would rely on a sample file, not
  a synth. Don't build on it.

### 1.9 The real lesson the project teaches for glitch design

Three transferable patterns, all zero-random:

1. **Parameter evolution by stepping a list one value per bar** —
   `.gain("<0 .16 .18 .20 .22 .24 0 0>")`, `.lpf("<500 600 750 950 1200 1500 0 0>")`.
   For you: bake each glitch as a **keyframed parameter list**, not as noise.
2. **Long LFOs for continuous motion** — `sine.range(a,b).slow(4..24)`, `sine.range(a,b).fast(1)`.
   For you: every always-on bed parameter gets a slow deterministic LFO.
3. **Contrast by sudden vacuum** — the "fake stop": `rending.strudel:399-418`,
   `shattered_mirror.strudel:337-343`, and `pan_rain/a_full.strudel:12-15`
   (*"顿停 12 单位 = 1.67 秒全静"* — 1.67 s of total silence before the eight-instrument
   downbeat). A horror crash that *cuts the noise bed to −∞* for 300–800 ms and then slams
   it back is worth more than any amount of extra distortion.

---

## 2. DSP recipes (exact math)

Sample rate `fs = 48000`. Everything below is per-sample, branch-free enough for Python.

### 2.1 Noise generators — verbatim from SuperDough 1.2.6 `noise.mjs`

`noise.mjs` builds **2 seconds** of mono noise in a `Float32Array` and loops it forever,
then a **fixed gain of `0.3`** is applied to every noise synth
(`synth.mjs registerSynthSounds`: `const g = gainNode(0.3);` — *"turn down"*).
So `s("white").gain(1)` peaks at ±0.3, not ±1. Reproduce that or your levels won't match.

**White** (uniform, not Gaussian):
```python
u = rng.uniform(-1.0, 1.0)          # JS: Math.random()*2-1
```

**Brown** (leaky integrator, exact coefficients):
```python
white = rng.uniform(-1.0, 1.0)
out   = (last_out + 0.02 * white) / 1.02
last_out = out
```
The `1.02` denominator makes it a stable one-pole at DC with H(z) ≈ 0.02/(1 − 0.9804 z⁻¹)
→ **−6 dB/oct**, with a −3 dB point near `fs·0.02/(2π·1.02) ≈ 150 Hz`. Very dark rumble.

**Pink** (Paul Kellet's refined 7-pole filter, exact coefficients as shipped):
```python
white = rng.uniform(-1.0, 1.0)
b0 = 0.99886*b0 + white*0.0555179
b1 = 0.99332*b1 + white*0.0750759
b2 = 0.96900*b2 + white*0.1538520
b3 = 0.86650*b3 + white*0.3104856
b4 = 0.55000*b4 + white*0.5329522
b5 = -0.7616*b5 - white*0.0168980
out = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white*0.5362) * 0.11
b6 = white * 0.115926
```
`*0.11` keeps the output in roughly ±1. **−3 dB/oct**, and this is the right bed material.

**Crackle** (this is the "vinyl/Geiger" texture — implement this exactly):
```python
probability = density * 0.01        # SuperDough default density = 0.03 -> p = 3e-4
out = rng.uniform(-1,1) if rng.random() < probability else 0.0
```
At `density = 0.03` you get ≈ **14.4 crackles per second**, each a single-sample impulse of
uniform amplitude. That is the missing "质感" ingredient: it is *sparse impulses*, i.e.
broadband, not a hiss. To shape it, never filter the impulses away — route crackle through
a **resonant band-pass** to give each click a body (§2.3), and a **short comb** (§2.6) to
give it a room. `density` is the only control `crackle` reads.

**Pink *mix* control** (`noise.mjs getNoiseMix` + `synth.mjs getOscillator`): any waveform
synth accepts `noise` ∈ [0,1] which cross-fades the oscillator with **looping pink noise**
using `drywet()`, whose law is not linear:
```js
wetfade = d => d < 0.5 ? 1 : 1 - (d-0.5)/0.5     // helpers.mjs
dry_gain = wetfade(wetAmount);  wet_gain = wetfade(1 - wetAmount)
```
So `noise = 0.5` → dry 1.0 + wet 1.0 (**6 dB louder**), `noise = 0.75` → dry 0.5, wet 1.0.
Worth cloning if you want your hum to be "sine + pink".

### 2.2 One-pole and state-variable filters (cutoff + resonance)

**One-pole low-pass** (use for the bed's rumble floor, and for smoothing any control):
```
g = 1 - exp(-2*pi*fc/fs)                 # alternative: g = 2*pi*fc/fs for fc << fs
y[n] = y[n-1] + g * (x[n] - y[n-1])
```
**One-pole high-pass** (same `g`): `y[n] = g * (y[n-1] + x[n] - x[n-1])`.

**Two-pole state-variable filter — this is literally the algorithm Strudel ships for
DJ filtering** (`superdough/worklets.mjs`, class `TwoPoleFilter`), and it gives you LP + BP
+ HP simultaneously from two states. Use it as your workhorse:

```
# per sample, per channel:
c  = clamp(2 * sin(fc * pi / fs), 0, 1.14)      # fc = cutoff in Hz, clamped to fs/2 - 1
r  = 0.5 ** ((res + 0.125) / 0.125)             # res in [0,1]; res=0 -> r=0.5, res=1 -> r=0.03125
mrc = 1 - r*c
s0 = mrc*s0 - c*s1 + c*x        # band-pass state
s1 = mrc*s1 + c*s0              # low-pass state
lp = s1
bp = s0
hp = x - s1                     # (DJF worklet uses exactly this: input - s1)
```
Note `res` here is a **0..1 damping knob, inverted relative to Q** — `res = 1` is the
resonant extreme. Strudel's `djf` control hardcodes `res = 0.1` and maps the slider to
`cutoff = (v*11)**4` (so a 0..1 slider spans 0 → 2.3 MHz; useful only as a shape).

**If you want a true Q:** a Chamberlin SVF with
`f = 2*sin(pi*fc/fs)`, `q = 1/Q`, then
```
lpn = lpn + f*bpn
hpn = x - lpn - q*bpn
bpn = f*hpn + bpn
```
stable for `f < 2 - q` (i.e. `fc < ~fs/4` at Q=1; clamp `f` to 0.99).

**RBJ biquad** (what Web Audio's `BiquadFilterNode` is, and therefore what every
`.lpf(...)` in the project sounds like) — coefficients for LPF:
```
w0    = 2*pi*fc/fs
alpha = sin(w0) / (2*Q)
b0 = (1 - cos(w0))/2 ; b1 = 1 - cos(w0) ; b2 = (1 - cos(w0))/2
a0 = 1 + alpha       ; a1 = -2*cos(w0) ; a2 = 1 - alpha
# normalise by a0; Direct Form I:
y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
```
HPF: `b0 = (1+cos w0)/2, b1 = -(1+cos w0), b2 = (1+cos w0)/2`, same `a`.
BPF (constant 0 dB peak gain): `b0 = alpha, b1 = 0, b2 = -alpha`, same `a`.
`Q` is the dB-peak knob; Strudel's default `resonance = 1` (Q=1, Butterworth-ish) and
`bandq = 1`. **A `.lpf(1200)` in Strudel is one RBJ biquad at 1200 Hz with Q=1.**

**Strudel's 4-pole tanh ladder** (`worklets.mjs LadderProcessor`), if you want the
"咬弦" bite — implement with the fast tanh it uses:
```python
def fast_tanh(x):
    x2 = x*x
    return (x*(27.0 + x2)) / (27.0 + 9.0*x2)
# setup
cutoff = min(1.0, fc * 2*pi / fs)
drive  = clamp(exp(drive_param), 0.1, 2000)      # drive_param default 0.69 -> ~2.0
k      = min(8, Q * 0.13)
makeup = (1/drive) * min(1.75, 1 + k)
# per sample
out = p3*0.360891 + p32*0.41729 + p33*0.177896 + p34*0.0439725
p34, p33, p32 = p33, p32, p3
p0 += (fast_tanh(x*drive - k*out) - fast_tanh(p0)) * cutoff
p1 += (fast_tanh(p0) - fast_tanh(p1)) * cutoff
p2 += (fast_tanh(p1) - fast_tanh(p2)) * cutoff
p3 += (fast_tanh(p2) - fast_tanh(p3)) * cutoff
y = out * makeup
```
This is your best "destructive resonance" tool: high `Q` + `drive 2..6` + the cutoff swept
upward produces self-oscillation-ish howl that stays musical because of the tanh.

### 2.3 Resonant band-pass for glitch bodies (cheap and effective)

Instead of writing a biquad per voice, the classic 2-pole resonator gives you a *ringing*
"body" per impulse — ideal for turning crackle into knocks and for the "comb resonance"
glitch:

```
R  = exp(-pi * bw / fs)          # bw = -3 dB bandwidth in Hz (choose 60..800)
th = 2*pi * f0 / fs              # f0 = centre in Hz
a1 = 2*R*cos(th)
a2 = -R*R
gain = (1 - R) * sqrt(1 - a1*R + a2*R*R)   # optional unity-peak normalisation
y[n] = gain*x[n] + a1*y[n-1] + a2*y[n-2]
```
Decay time constant: `tau ≈ 1/(pi*bw)` seconds (`bw = 100 Hz` → `tau ≈ 3.2 ms`;
`bw = 20 Hz` → 16 ms; `bw = 5 Hz` → 64 ms). Sweeping `f0` across 200 → 6000 Hz with
`bw = 40` on white noise is the single most convincing "metal being stressed" sound you
can make with 5 lines of arithmetic.

### 2.4 ADSR — implement SuperDough's semantics exactly

Use the state machine from §1.3. Two practical additions:
- **Linear for amplitude, exponential for cutoff.** `y = ymin * (ymax/ymin)**t` with
  `ymin = 0.001`.
- **Anti-click always:** every parameter change (glitch onset, gate, filter jump) gets a
  **2–10 ms linear ramp**, not a step. Web Audio does this implicitly via
  `setValueAtTime` + ramp; a raw Python mixer must do it by hand or every glitch will
  click — and clicks are what make cheap glitches sound cheap.

Minimal frame-based implementation (control rate 1 kHz is plenty; sample-accurate is not):
```python
class Ramp:
    def __init__(self, v=0.0): self.v = v; self.target = v; self.step = 0.0
    def to(self, target, ms, fs_ctrl):
        self.target = target
        n = max(1, int(ms * fs_ctrl / 1000))
        self.step = (target - self.v) / n
    def tick(self):
        if self.v != self.target:
            self.v += self.step
            if (self.step > 0 and self.v > self.target) or (self.step < 0 and self.v < self.target):
                self.v = self.target
        return self.v
```

### 2.5 Waveshapers — verbatim from SuperDough `helpers.mjs` / `worklets.mjs`

Named `distorttype` indices in the order SuperDough registers them:
`0 scurve, 1 soft, 2 hard, 3 cubic, 4 diode, 5 asym, 6 fold, 7 sinefold, 8 chebyshev`.
All are called as `postgain * algo(x, k)` with **`k = expm1(distort)`** (so `distort = 0`
→ `k = 0` = clean; `distort = 1` → `k = 1.718`; `distort = 2` → `k = 6.389`;
`distort = ln(50) ≈ 3.9` → `k ≈ 49`). `postgain = distortvol`, default 1.

```python
squash = lambda x: x / (1 + x)                       # [0,inf) -> [0,1)
mod    = lambda n, m: ((n % m) + m) % m
soft   = lambda x, k: math.tanh(x * (1 + k))
scurve = lambda x, k: ((1 + k) * x) / (1 + k * abs(x))
hard   = lambda x, k: clamp((1 + k) * x, -1, 1)
fold   = lambda x, k: 1 - abs(mod((1 + 0.5*k)*x + 1, 4) - 2)
sinefold = lambda x, k: math.sin((math.pi/2) * fold(x, k))

def cubic(x, k):
    t = squash(math.log1p(k))
    c = (x - (t/3)*x*x*x) / (1 - t/3)
    return soft(c, k)

def diode(x, k, asym=False):
    g = 1 + 2*k
    t = squash(math.log1p(k))
    bias = 0.07 * t
    pos = soft(x + bias, 2*k)
    neg = soft(bias if asym else -x + bias, 2*k)
    y = pos - neg
    sech = 1 / math.cosh(g * bias)
    denom = max(1e-8, (1 if asym else 2) * g * sech*sech)
    return soft(y / denom, k)

def chebyshev(x, k):
    kl = 10 * math.log1p(k)
    tnm1, tnm2, y = 1.0, x, 0.0
    for i in range(1, 64):
        if i < 2:
            y += tnm1 if i == 0 else tnm2
            continue
        tn = 2*x*tnm1 - tnm2
        tnm2, tnm1 = tnm1, tn
        if i % 2 == 0:
            y += min((1.3*kl)/i, 2.0) * tn
    return soft(y, kl/20)
```

**Recommended for analog horror:** `diode` / `asym` (adds even harmonics — "broken
transformer"), `fold` / `sinefold` (aliasing-rich, digital scream), `chebyshev` (metallic
ring-mod-ish upper harmonics). `hard` at high `k` is the "cheap" sound you're trying to
escape — use it only as a *final* safety net before the limiter, never as the character.

The simple tanh shaper SuperDough uses for its `sbd` drum
(`makeSaturationCurve`): `curve[i] = tanh(x * k)` with `k = 2` for the diode-ish tri→sine
emulation, `k = 50` by default.

### 2.6 Bitcrush + decimation — exact SuperDough semantics

```python
# crush: bit-depth reduction.  crush = 1 -> everything becomes 0/-1 (max destruction)
x_q   = 2 ** (crush - 1)
out   = round(x * x_q) / x_q

# coarse: sample-and-hold.  out_delay = (coarse - 1) / fs  seconds
coarse = max(1, int(round(coarse)))          # MUST be an integer number of samples
if n % coarse == 0: hold = x
out = hold
```
Relation to the usual "bit depth" language: `crush = B + 1`, where `B` is the bit count —
`crush 8` → 7-bit (128 levels, clearly lo-fi), `crush 4` → 3-bit (9 levels, destroyed),
`crush 12` → 11-bit (subtle). SuperDough's default `crush = 0` **is clamped to 1**, so
sending `crush(0)` is maximum damage, not "off" — omit the control to bypass.

For the *audible* effect, combine both: `crush 5–7` alone sounds like a cheap 80s sampler;
`crush 5–7` followed by a **band-pass at 1.5–4 kHz** and a **short comb** sounds like a
dying intercom. Add **sample-rate reduction *before* the waveshaper**, not after, or the
aliasing gets masked.

### 2.7 Vowel / formant bank — exact table from SuperDough `vowel.mjs`

5 parallel RBJ **band-pass** filters (`Q = qs[i]`), each through a gain `gains[i]`, all
summed into a makeup gain of **8**. This is a genuinely good "possessed voice" engine for
a terminal demo — feed it the noise bed, not a vocal.

| vowel | freqs (Hz) | gains | Qs |
| --- | --- | --- | --- |
| a | 660, 1120, 2750, 3000, 3350 | 1, 0.5012, 0.0708, 0.0631, 0.0126 | 80, 90, 120, 130, 140 |
| e | 440, 1800, 2700, 3000, 3300 | 1, 0.1995, 0.1259, 0.1, 0.1 | 70, 80, 100, 120, 120 |
| i | 270, 1850, 2900, 3350, 3590 | 1, 0.0631, 0.0631, 0.0158, 0.0158 | 40, 90, 100, 120, 120 |
| o | 430, 820, 2700, 3000, 3300 | 1, 0.3162, 0.0501, 0.0794, 0.01995 | 40, 80, 100, 120, 120 |
| u | 370, 630, 2750, 3000, 3400 | 1, 0.1, 0.0708, 0.0316, 0.01995 | 40, 60, 100, 120, 120 |
| ae | 650, 1515, 2400, 3000, 3350 | 1, 0.5, 0.1008, 0.0631, 0.0126 | 80, 90, 120, 130, 140 |
| aa | 560, 900, 2570, 3000, 3300 | 1, 0.5, 0.0708, 0.0631, 0.0126 | 80, 90, 120, 130, 140 |
| oe | 500, 1430, 2300, 3000, 3300 | 1, 0.2, 0.0708, 0.0316, 0.01995 | 40, 60, 100, 120, 120 |
| ue | 250, 1750, 2150, 3200, 3300 | 1, 0.1, 0.0708, 0.0316, 0.01995 | 40, 60, 100, 120, 120 |
| y  | 400, 1460, 2400, 3000, 3300 | 1, 0.2, 0.0708, 0.0316, 0.02995 | 40, 60, 100, 120, 120 |
| uh | 600, 1250, 2100, 3100, 3500 | 1, 0.3, 0.0608, 0.0316, 0.01995 | 40, 70, 100, 120, 130 |
| un | 500, 1240, 2280, 3000, 3500 | 1, 0.1, 0.1708, 0.0216, 0.02995 | 40, 60, 100, 120, 120 |
| en | 600, 1480, 2450, 3200, 3300 | 1, 0.15, 0.0708, 0.0316, 0.02995 | 40, 60, 100, 120, 120 |
| an | 700, 1050, 2500, 3000, 3300 | 1, 0.1, 0.0708, 0.0316, 0.02995 | 40, 60, 100, 120, 120 |
| on | 500, 1080, 2350, 3000, 3300 | 1, 0.1, 0.0708, 0.0316, 0.02995 | 40, 60, 100, 120, 120 |

Aliases: `æ→ae`, `ø→oe`, `ɑ/å→aa`, `ö→oe`, `ü→ue`, `ı→y`.

**Glitch use:** cross-fade `u → a → i` over 250 ms while the noise bed is bitcrushed and
ring-modulated and you have a "voice trying to speak through the static" — the single
highest-value trick in this document.

### 2.8 Comb / delay with feedback

```
# delay line of D samples (D may be fractional -> linear-interpolate the read)
y[n] = x[n] + g * read(buf, n - D)
buf[n] = y[n]                       # (write-after-read to allow g >= 1 unstable scream)
```
- `D = fs / f0` → **resonant comb**, peaks at `f0, 2f0, 3f0…`. This is the "metallic pipe"
  sound. `g = 0.7..0.97`, `D` swept → the classic "warp/desync" whoosh.
- `D = 30..600 ms`, `g = 0.35..0.75` → **echo/delay**. Strudel's default
  `delayfeedback = 0.5`, and the project always uses `delaytime = one beat`
  (`delaytime(5/9)` = 0.5556 s at 108 BPM, `pan_rain/*`).
- **All-pass** (Schroeder, used in reverb): `y[n] = -g*x[n] + x[n-D] + g*y[n-D]`.
- **Stability:** keep `|g| < 1` for anything you don't want to grow. For a horror demo,
  allow `g = 1.02..1.05` on a *comb* for 200–600 ms and hard-limit the output — the
  exponential self-oscillation then reads as feedback howl rather than as a bug.

### 2.9 Ring modulation / AM / tremolo

```
ring:    y[n] = x[n] * sin(2*pi*fm*n/fs)             # fm 30..400 Hz = inharmonic metal
                                                # fm 8..40 Hz  = "wobble"/desync
AM/gate: y[n] = x[n] * (dc + depth * sin(2*pi*fm*n/fs))   # dc = 1 - depth, so it never inverts
```
SuperDough's `tremolo` is exactly the AM form with a **clipped** modulator, which is the
detail worth copying: `gain = max(1 - depth, 0)`, LFO shaped by `curve = 1.5` and clamped
to `[0,1]`, i.e. `mod = clamp((shape(phase) + 0)^1.5, 0, 1)` with `shape` ∈
{tri, sine, ramp, saw, square}. A **`square` shape at depth 1** is the stutter/gate;
a **`sine` at depth 0.3–0.6** is the jelly-wobble. Defaults if you set `tremolo`:
`tremolodepth = 1`, `tremolophase = 0`.

`apulsator`-style stereo AM (only in ffmpeg, not SuperDough): use two modulators 90°
apart on L/R for a rotating/vomiting effect.

### 2.10 Pitch shift by playback rate — and the phase-vocoder alternative

**Naive (what `speed` does in the sampler):** resample `x[n·r]` with linear interpolation,
`r = 2**(semitones/12)`. Duration scales by `1/r` and *formants move with it* — which is
exactly the "tape slowing down / power dying" sound you want for the horror drop.
```python
def resample(x, r, i0, n):
    pos = i0
    out = []
    for _ in range(n):
        i = int(pos); f = pos - i
        out.append(x[i]*(1-f) + x[i+1]*f)
        pos += r
    return out
```
Add **tape flutter** by making `r` wobble: `r *= 1 + 0.004*sin(2*pi*6.3*n/fs)` (# wow) and
`1 + 0.0015*sin(2*pi*0.7*n/fs)` (flutter).

**Formant-preserving (SuperDough `stretch` → `phase-vocoder-processor`,
`worklets.mjs`):** FFT size 2048, Hann window ×1.62, hop = blockSize/4 =
512 (from `OLAProcessor`), peak-picking with 2-bin suppression, then
`shiftPeaks(pitchFactor)` with phase correction
`omegaDelta = 2*pi*(binShifted - bin)/fftSize`, `phaseShift = e^{i·omegaDelta·timeCursor}`.
Also note the sign convention: **`pitchFactor < 0` is multiplied by 0.25** before
`pitchFactor = max(0, pitchFactor + 1)`, so `stretch(-4)` = quarter-speed shift and
`stretch(-1)` = unity. Stdlib-only Python: an OLA without phase locking (Hann ×1.62,
75 % overlap) is achievable with pure `cmath`/no numpy only at painful CPU cost; prefer
§2.10's naive resampler plus a **fixed formant bank** (§2.7) if you want both.

### 2.11 Reverb — Schröder / Freeverb, concrete numbers

SuperDough uses a **generated convolution IR** with these controls
(`superdough/reverb.mjs` → `createReverb(duration, fade, lp, dim, ir, irspeed, irbegin)`
calling `reverbGen.generateReverb({decayTime, fadeInTime, lpFreqStart, lpFreqEnd})`):
`room` = send amount, `roomsize` = decay time, `roomfade` = fade-in, `roomlp` = LP start
(default **15000**), `roomdim` = LP end (default **1000**). **The IR darkens from 15 kHz to
1 kHz as it decays** — that is the whole "analog" character. Recreate that behaviour
explicitly: a reverb whose damping increases over the tail.

Cheapest faithful structure (per channel):
```
# 4 parallel combs (prime-ish delays, mono L; R uses the Freeverb +23 sample offset)
comb delays (L, samples @48k):  1557, 1617, 1491, 1422   (tuned for 44.1k; scale by fs/44100 -> 1694, 1760, 1623, 1547)
comb feedback g:                g = 10 ** (-3 * D / (decay_time * fs))    # D in samples
allpass in series:              delays 225, 556, 441, 341  (scale by fs/44100), g = 0.5
# per-comb one-pole damping: y = y + d*(x - y)  with d = 0.2..0.5  (this is the "dim")
```
The comb feedback formula `g = 10^(-3*D/(t60*fs))` gives an exact, controllable decay:
`t60 = 0.8 s` (small room), `2.5 s` (hall), `6 s` (cathedral). For horror, use
`t60 = 3..8 s` on the noise bed and **high-pass the reverb send at 300 Hz** so the rumble
doesn't turn to mud.

Simplest usable alternative if CPU is tight: **3 combs + 2 allpasses**, `t60 = 4 s`,
`d = 0.35`, with the send high-passed at 250 Hz and the return low-passed at 6 kHz and
swept down to 1.2 kHz over the tail. That is 90 % of the perceived quality.

### 2.12 Ring mod + comb + crush combined, and a DC blocker

Every glitch should end with a DC blocker or your bitcrusher will inject offset into
ffplay (audible as a thump at gate edges, and it eats headroom):
```
y[n] = x[n] - x[n-1] + 0.995 * y[n-1]        # one-pole HP at ~38 Hz @48k
```

---

## 3. The "noise bed that glitches" architecture

### 3.1 Signal graph

```
                    ┌─ brown  (0.98 one-pole @ ~150 Hz)  ──┐
 noise bank (free)  ├─ pink   (Kellet, exact coeffs)      ─┤
 2 s buffers, loop  ├─ white  (uniform)                    ├─► [ voice = per-glitch copy? no ]
                    └─ crackle(density)                     │
                                                            ▼
                                    ┌──────────────────────────────────────────┐
                                    │ SOURCE BUS (mono, 1 copy only)          │
                                    │  mix: brown .55 / pink .40 / white .08  │
                                    │       crackle .15   (all pre-gain)      │
                                    └────────────────┬─────────────────────────┘
                                                     │
   ┌─────────────────────────────────────────────────┴──────────────────────────┐
   │ BED CHAIN  (always on, one instance, "BGM" role)                           │
   │  HP 26 Hz → LP slow-LFO (300→3400 Hz, 18 s) → notch 50 Hz (mains hum) →    │
   │  shape(0.12) → bed_gain (LFO 0.30±0.05, 11 s) →                            │
   │  ── split L/R by 12 ms Haas delay (L = dry, R = +12 ms, 0.35 gain)  ──     │
   │  → reverb send 0.35 (t60 4.5 s, send HP 250 Hz, return LP 6 kHz→1.2 kHz)   │
   │  → bed bus                                                                 │
   └────────────────────────────────────────────────────────────────────────────┘
                                                     │
   ┌─────────────────────────────────────────────────┴──────────────────────────┐
   │ GLITCH CHAIN (one voice, retriggerable; ~6-8 voice pool)                   │
   │  tap SOURCE BUS (pre-bed-gain) →                                           │
   │   [G1 pitch/rate] → [G2 ringmod] → [G3 resonant BP/comb sweep] →            │
   │   [G4 crush+coarse] → [G5 shaper/fold] → [G6 gate/stutter + reverse] →      │
   │   [G7 width/pan/HAAS-collapse] → [G8 gain env + click-safe ramps] →         │
   │   → reverb send per-family → glitch bus                                     │
   └────────────────────────────────────────────────────────────────────────────┘
                                                     │
                       GLITCH BUS + BED BUS → master (soft-clip → limiter −1 dBTP → s16)
                                                     │
                                          duck: glitch env → bed_gain (−6 dB, 25 ms att)
```

Two rules that make this work:

**Rule 1 — the glitch chain taps the bus *before* the bed's gain LFO.** Otherwise the bed's
slow amplitude modulation modulates the glitch too.

**Rule 2 — the bed is ducked by every glitch, not just mixed with it.** A −4 to −8 dB duck
with 5 ms attack and 120–400 ms release is what makes a glitch feel like it *interrupted*
the world. This is SuperDough's `duckorbit`/`duckonset`/`duckattack`/`duckdepth` mechanism,
and it is the cheapest single upgrade to perceived production value.

### 3.2 Glitch voice parameter set + recommended ranges

Every glitch is one `GlitchEvent` = a keyframe list per parameter. All times in ms,
all gains in dB (convert at the end: `lin = 10**(dB/20)`).

| Block | Parameter | Range | Default | Unit |
| --- | --- | --- | --- | --- |
| source mix | `brown/pink/white/crackle` | 0..1 each | .55/.40/.08/.15 | lin |
| G1 rate | `speed` | 0.25 .. 4.0 (0.25 = −24 st, 4.0 = +24 st) | 1.0 | ratio |
| | `speed_slew` | 1 .. 2000 | 80 | ms per octave |
| G2 ring | `rm_freq` | 0.5 .. 12 Hz (wobble) / 30 .. 900 Hz (metal) | 55 | Hz |
| | `rm_depth` | 0 .. 1 | 0.85 | lin |
| G3 filter | `bp_center` | 30 .. 8000 | 900 | Hz |
| | `bp_bw` | 5 .. 1500 | 60 | Hz |
| | `comb_delay` | 0.2 .. 40 | 3.0 | ms |
| | `comb_fb` | −0.98 .. 1.04 | 0.92 | lin |
| G4 crush | `crush` | 2 .. 16 (bits+1) | 6 | — |
| | `coarse` | 1 .. 96 (hold length in samples) | 1 | samples |
| G5 shaper | `distort` | 0 .. 4.5 (`k = expm1`) | 1.6 | — |
| | `distorttype` | 0 scurve, 1 soft, 2 hard, 3 cubic, 4 diode, 5 asym, 6 fold, 7 sinefold, 8 cheb | 5 (asym) | — |
| | `shape` | 0 .. 0.95 | 0.3 | — |
| G6 gate | `gate_rate` | 2 .. 60 | 18 | Hz |
| | `gate_depth` | 0 .. 1 | 1.0 | lin |
| | `gate_shape` | square / saw / tri / sine | square | — |
| | `reverse` | 0/1 (per 20–200 ms micro-buffer) | 0 | — |
| G7 width | `width` | −1 .. 1.5 (0 = mono-ish, 1 = normal, <0 = out-of-phase) | 1.0 | lin |
| | `pan` | 0 .. 1 (0.5 = centre) | 0.5 | — |
| | `haas` | 0 .. 30 | 8 | ms |
| G8 env | `attack` | 0.5 .. 400 | 3 | ms |
| | `release` | 5 .. 6000 | 220 | ms |
| | `peak` | −40 .. −3 | −9 | dBFS |
| send | `room` | 0.10 .. 0.95 | family-dependent | lin |
| | `t60` | 0.6 .. 9 | 3.5 | s |
| duck | `duck_db` | 0 .. −12 | −6 | dB |
| | `duck_att/rel` | 2..20 / 60..600 | 5 / 250 | ms |

### 3.3 The five named glitches, as keyframe recipes

Notation: `t=0` is onset; `x→y @ Tms` means ramp to `y` reached at `T` ms.
`rev(line)` = reverse-read the pre-glitch 30–180 ms tail. `⊘` = parameter bypassed.

**A. STATIC BURST** — "signal lost" — 90–250 ms. Family: short, dry-ish.
```
speed   1.0
rm      rm_freq 30→140 Hz, rm_depth 0.9
bp      bp_center 8000→3000 @ 120ms, bp_bw 900→250 @ 120ms
comb    comb_delay 0.4ms, comb_fb 0.85
crush   crush 4 (→ 6 @ 200ms), coarse 3 (→ 1 @ 200ms)
distort 3.8, distorttype 2 (hard), shape 0.0
gate    gate_rate 0→45 Hz, depth 1.0, square
env     attack 0.8 ms, release 60 ms, peak −7 dBFS
send    room 0.25, t60 1.2 s, duck −7 dB @ 3/180 ms
```
Sounds like: a radio being unplugged. The `rm at 30→140 Hz` is what separates this from
plain "hiss" — it puts a growl under the top end.

**B. WARP / DESYNC SWEEP** — the "tape spooling" one — 400–2500 ms.
```
speed   0.42→2.4 @ 900ms (slew 120 ms/oct)   # or reverse: 2.4→0.42
rm      rm_freq 5→38 Hz (slow, deep), rm_depth 0.55
bp      bp_center 200→7000 @ 800ms then → 400 @ 1800ms, bp_bw 40
comb    comb_delay 12→0.6ms in 140 discrete steps (this IS the "desync")
crush   crush 7, coarse 2
distort 1.2, distorttype 4 (diode), shape 0.35
gate    ⊘
env     attack 2 ms, release 900 ms, peak −10 dBFS
send    room 0.55, t60 3.0 s, duck −5 dB @ 5/500 ms
```
Sounds like: a VHS tape eating itself. The comb-delay ladder is the load-bearing detail;
a plain pitch sweep alone sounds like a $5 plugin.

**C. TICK** — the punctuation mark — 8–35 ms. Family: ultra-short, no reverb.
```
speed   1.0
rm      ⊘
bp      bp_center 2600 Hz, bp_bw 380 (fixed; the "body" of the click)
comb    ⊘
crush   crush 9, coarse 1
distort 0.6, distorttype 0 (scurve)
env     attack 0.3 ms, release 12 ms, peak −14 dBFS
send    room 0.06, t60 0.6 s, duck 0 (a tick should NOT duck the bed — save that for events)
```
Sounds like: a Geiger counter / relay. **Vary only `bp_center` (2000–4200 Hz) and the
interval (60–400 ms, jittered from a deterministic prime-step pattern, per §1.9 rule 1).**
Randomising amplitude here is what makes cheap ticks sound cheap.

**D. HUM** — the sustained dread — 1.5–12 s, the only glitch that is a *state*, not an event.
```
source  brown .75 / pink .25 / white .02
speed   1.0
rm      rm_freq 50.0 Hz (mains!), rm_depth 0.35   # or 60.0 for US/EU flavour switch
bp      bp_center 50 Hz (then slide to 47 Hz over 6 s = "sagging mains")
        + parallel bp at 150 / 250 Hz (harmonics) via 3 summed resonators, bw 4 Hz
comb    comb_delay 20 ms, comb_fb 0.94
crush   8
distort 1.8, distorttype 5 (asym)   # asym adds even harmonics = "not a clean sine"
env     attack 400 ms, release 1200 ms, peak −20 dBFS
send    room 0.45, t60 6 s (send HP 300 Hz)
```
Sounds like: a building with something wrong in the basement. Slide the mains frequency by
1–3 Hz over the whole demo and it becomes genuinely unsettling. **You can keep this running
under the bed at −26 dBFS permanently and just raise it during the crash** — that satisfies
your requirement (b) "glitches are processing of the noise" perfectly.

**E. IMPACT** — the crash-down — 600–4000 ms. Family: long, wet.
```
source  brown .6 / pink .3 / white .1 (white only for the first 40 ms)
speed   1.0→0.30 @ 2500ms
rm      rm_freq 90 Hz, rm_depth 0.7, then rm_freq 90→24 Hz @ 1500ms
bp      bp_center 120→45 Hz @ 1200ms, bp_bw 120→30
comb    comb_delay 24→3 ms @ 300ms
crush   crush 5 for first 120 ms, then 10
distort 3.0, distorttype 4 (diode), shape 0.5
gate    gate_rate 0 (bypass)
env     attack 4 ms, hold, release 2200 ms, peak −5 dBFS
send    room 0.9, t60 8 s, duck −10 dB @ 4/700 ms
```
Sounds like: something enormous arriving. The `speed 1.0 → 0.30` over 2.5 s plus the room
tail is the whole trick; no one shots needed.

### 3.4 Structure of the always-on bed: exact numbers

| Layer | Source | Chain | Steady level |
| --- | --- | --- | --- |
| Rumble | brown | 1-pole LP 120 Hz, HP 26 Hz | −30 dBFS |
| Body | pink | BP 180–5000 Hz (two RBJ: HP 180, LP 5000) | −33 dBFS |
| Hiss | white | HP 7 kHz, LP 12 kHz, then `shape(0.15)` | −42 dBFS |
| Texture | crackle `density 0.02–0.05` | BP 1800 Hz bw 500, 1 short comb 8 ms fb 0.7 | −34 dBFS peak (impulsive) |
| Room | (all of the above) | reverb send 0.35, t60 4.5 s, send HP 250 Hz, return LP 6 kHz→1.2 kHz | −36 dBFS wet |

**Slow deterministic LFOs on the bed** (this is what kills "flat", per §1.1):
- `bed_lp`: `sine.range(2800, 6000)` over **37 s** (prime-ish period so it never lines up
  with the visuals) — one sines.range LFO, not a random walk.
- `bed_gain`: `0.30 * (1 + 0.18*sin(2π t / 23 s))` — an 11 dB-slow breathing.
- `bed_pan`: `0.5 + 0.09*sin(2π t / 41 s)`.
- `hiss_gain`: `−42 dB + 3 dB * (0.5 + 0.5*sin(2π t / 7 s))`.
- `crackle_density`: a fixed stepping list of 8 values cycling every 8 s
  (`[.02 .05 .02 .07 .03 .02 .09 .04]`) — §1.9 rule 1, zero random.

Master chain (final):
```
sum(bed, glitch) → sum gain 0.9 → DC blocker (0.995) →
soft clip tanh(k=1.6) → lookahead-free limiter (ceil −1.0 dBFS, release 80 ms) →
write s16le stereo
```
Watch the arithmetic: 4 noise layers at −30 dBFS **sum incoherently** (+3 dB per doubling
if uncorrelated), so the bed as built is ≈ −24 dBFS RMS. Leave that headroom; the glitches
peak at −5 and everything goes through the limiter.

---

## 4. ffmpeg post-processing (verified on this machine)

Verified on this host: `ffmpeg`, **`ffmpeg version 2025-03-31-git-35c091f4b7-full_build-www.gyan.dev`**
(7.x-era, gyan full build). No `pnpm`/network needed. Full config flags relevant here:
`--enable-librubberband --enable-ladspa --enable-libsoxr --enable-gpl --enable-version3`.

All filters below are **present in this build** (I checked `-filters` and dumped each
filter's options, so the parameter names/ranges are the real defaults, not guesses):
`aecho acompressor alimiter aphaser chorus areverse adelay rubberband loudnorm tremolo
vibrato highpass lowpass bandpass acrusher asoftclip aeval aexciter afftdn acontrast
adynamicsmooth apulsator aphaseshift stereotools stereowiden extrastereo haas firequalizer
equalizer superequalizer asubboost adeclip virtualbass dynaudnorm anequalizer`.

`afir` exists but is `N->A` — it needs a **second input stream** of FIR coefficients, so it
is *not* a drop-in reverb. For an IR reverb use `-i ir.wav` + `afir` with the IR as the
second input, or just skip it: `aecho` + `apulsator` + `asoftclip` gets you there in one
input. `rubberband` **is** available (`--enable-librubberband`) — that is the one you asked
about and it is usable without an external dependency.

### 4.1 The analog-horror master chain (recommended, exact)

Single filtergraph, `mix.wav` (stereo, whatever rate) → `out.wav`. Insert `-ar 48000` on
output. Line-broken for readability; ffmpeg accepts the newlines inside the quoted graph.

```
ffmpeg -y -i mix.wav -af "
  firequalizer=gain='if(lt(f,35),-60,if(lt(f,60),-6*(60-f)/25,if(lt(f,4000),0,-10*(f-4000)/11000)))':delay=0.05:accuracy=10:zero_phase=1,
  equalizer=f=50:width_type=o:width=1.2:g=2.5,
  equalizer=f=180:width_type=o:width=1.0:g=-2,
  equalizer=f=3200:width_type=o:width=1.0:g=2,
  acompressor=threshold=0.09:ratio=3.5:attack=25:release=320:makeup=1.6:knee=3:detection=rms:link=average,
  aphaser=in_gain=0.5:out_gain=0.7:delay=2.5:decay=0.35:speed=0.18:type=s,
  aecho=0.75:0.35:180|430|790:0.5|0.32|0.18,
  stereowiden=delay=16:feedback=0.22:crossfeed=0.28:drymix=0.82,
  asoftclip=type=tanh:threshold=0.85:output=1.0:param=1.2:oversample=4,
  alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=120:asc=1:asc_level=0.6,
  loudnorm=I=-16:LRA=9:TP=-1.0:print_format=summary
" -ar 48000 -c:a pcm_s16le out.wav
```

**Both of these were run on this machine and produce `EXIT=0` plus a valid WAV** (I tested the
graph against `anoisesrc=c=pink`, 4 s, and it wrote 919,758 bytes). Measured response of the
`firequalizer` line above, relative to unfiltered, by sine sweep + `astats`:

```
 20 Hz = -30.1 dB     500 Hz = -0.4 dB    8000 Hz =  -4.1 dB
 35 Hz =  -9.1 dB    2000 Hz = -0.4 dB   12000 Hz =  -7.7 dB
 60 Hz =  -1.1 dB    4000 Hz = -0.4 dB   16000 Hz = -11.3 dB
125 Hz =  -0.4 dB                         20000 Hz = -15.0 dB
```
That is the intended analogue contour: a **2-pole-ish high-pass rolling off below ~60 Hz** and
a **~4 dB/octave roll-off above 4 kHz reaching −15 dB at 20 kHz**. Note the high-pass corner
is *soft* — `firequalizer` is a linear-phase FIR, so a `-60 dB` shelf at 35 Hz does not mean
silence at 50 Hz. If you need a hard subsonic cut, put `highpass=f=26:poles=1` **before** the
`firequalizer`.

> ⚠️ **Two corrections I made to my own first draft, both verified against this build:**
> 1. `bandpass` has **no `poles` option** — its AVOptions are `frequency/f, width_type/t,
>    width/w, csg, mix/m, channels/c, normalize/n, transform/a, precision/r, blocksize/b`.
>    Passing `poles=1` is a hard error: *`Error applying option 'poles' to filter 'bandpass':
>    Option not found`* → *`Error opening output file`*. `poles` exists only on
>    `highpass`/`lowpass` (range **1..2**).
> 2. `bandpass`'s `width_type=h:width=N` does **not** give a brick-wall band. Measured with
>    `bandpass=f=2500:width_type=h:width=6000`: `125 Hz −18.5 dB, 500 −7.1, 1000 −2.5,
>    2000 −0.2, 4000 −0.7, 8000 −4.5, 16000 −13.0` — i.e. only ~6 dB/octave skirts. It is a
>    *one-pole high-pass + one-pole low-pass* pair with a single `Q`. For a real band-limit,
>    use `firequalizer` as above, or `highpass` + `lowpass`, or `asupercut`/`asuperpass`.

What each piece is doing and why those numbers:

| Filter | Values | Why |
| --- | --- | --- |
| `firequalizer=gain='...'` | HP shelf −60 dB @ <35 Hz, flat to 4 kHz, then −10 dB slope to 20 kHz | the whole "analog vs. digital" character in one filter (see measured table). `delay=0.05` s must be ≥ the FIR length or you get pre-ringing; `zero_phase=1` removes the phase shift at the cost of latency; `accuracy=10` = fine interpolation of the curve |
| `equalizer=f=50 width_type=o width=1.2 g=2.5` | +2.5 dB @ 50 Hz, octave width | mains-hum reinforcement, matches the HUM glitch |
| `equalizer=f=180 g=-2` | −2 dB @ 180 Hz | declutter the mud where brown+impact pile up |
| `equalizer=f=3200 g=2` | +2 dB @ 3.2 kHz | the "presence"/intelligibility band for crackle and ticks |
| `bandpass=f=11000:width_type=h:width=9000` | ~~1-pole BP~~ **do not use alone** | **removed** — see the correction note above. If you want a gentle broadband air boost, prefer `highpass=f=6500:poles=1,lowpass=f=15500:poles=1` (measured: 1-pole cascade, only −3 dB/oct at 16 kHz) or an `aexciter` |
| `acompressor=threshold=0.09:ratio=3.5:attack=25:release=320:makeup=1.6` | thr −20.9 dBFS, 3.5:1, 25 ms / 320 ms | `threshold` is **linear** in ffmpeg (0.09 ≈ −20.9 dB), not dB. Slow-ish attack preserves transient crackle; 320 ms release = "breathing" glue |
| `aphaser=...:speed=0.18:type=s` | 0.18 Hz sine, 2.5 ms delay, decay 0.35 | 5.5 s cycle phase swirl — moving air, not an effect |
| `aecho=0.75:0.35:180\|430\|790:0.5\|0.32\|0.18` | in 0.75, out 0.35, 3 taps at 180/430/790 ms with decays .5/.32/.18 | `delays`/`decays` are `\|`-separated inside the graph (escape for the shell). 180 ms ≈ a small room; the 790 ms tap is the "hall behind the wall". out_gain 0.35 keeps it a send, not a wash |
| `stereowiden=delay=16:feedback=0.22:crossfeed=0.28:drymix=0.82` | 16 = 16 **ms**? — see caveat below | widens the mono bed into stereo |
| `asoftclip=type=tanh:param=1.2:oversample=4` | tanh, k=1.2, 4× OS | exactly the `soft` shaper from §2.5, computed with 4× oversampling in ffmpeg (which your Python mixer's naive version cannot do — **this is the one place ffmpeg is strictly better than your mixer**; it avoids the aliasing that makes naive clip sound cheap) |
| `alimiter=limit=0.891:attack=5:release=120:asc=1:asc_level=0.6` | −1.0 dBFS ceiling | `limit` is linear (0.891 = −1 dB). `asc=1` = automatic soft clipping, which is *not* a lookahead limiter — it adds harmonic content. Turn `asc` **off** (default `false`) if you want transparency; turn it on for character |
| `loudnorm=I=-16:LRA=9:TP=-1.0` | −16 LUFS, LRA 9 | target for "video/demo" loudness. **Use it last and single-pass**, or better: two-pass with `measured_*` if the length is fixed. `loudnorm` is a *linear* gain when `linear=true` (default) and the requested target is reachable, so it will not squash your dynamics |

**Caveat on `stereowiden.delay`:** the option help says `from 1 to 100 (default 20)` and the
documented unit is milliseconds of *feed-forward* delay. 16 ms is a strong widening; if the
result sounds phasey on mono playback, drop to `delay=6:crossfeed=0.15`.

**Caveat on `aphaser.delay`:** help says `from 0 to 5 (default 3)` ms. `speed` is
`0.1 to 2` Hz. `decay` `0 to 0.99`.

### 4.2 Reverb alternatives in ffmpeg

1. **`aecho` as a cheap reverb** (best cost/quality, single-input):
   ```
   aecho=0.8:0.25:40|97|163|281|503|797:0.7|0.6|0.5|0.4|0.3|0.2
   ```
   6 prime-ish taps, exponentially decaying — this is a sparse FIR reverb guess. Cheap and
   surprisingly good on noise.
2. **`afir` with a real IR** (needs a 2nd input stream):
   ```
   ffmpeg -i mix.wav -i hall_ir.wav -filter_complex "[0:a][1:a]afir=gtype=dc:irgain=-6:irnorm=1[out]" -map "[out]"
   ```
   `afir` is `N->A`, so the IR must be a **separate input**, not a filter argument. Generate
   an IR yourself in Python (exponentially decaying noise, `t60 = 4 s`, LP swept 15 k→1 k)
   and this becomes **exactly** the SuperDough reverb character from §2.11.
3. **`apulsator`** for a rotating/tumbling space (period in ms):
   ```
   apulsator=mode=triangle:level_in=1:level_out=1:offset_l=0:offset_r=0.25:width=1:timing=h:ms=700
   ```
   A 25 % L/R phase offset at 700 ms period is a slow, nauseating rotation — good for the
   "reality is a bit off" sections.
4. **`asubboost`** to restore sub weight lost to the HPF:
   `asubboost=dry=0.7:wet=0.4:decay=0.5:feedback=0.25:cutoff=90:slope=0.6:delay=12`.

### 4.3 Degradation / "tape & radio" chain

**Radio / intercom** (this is the chain for a "voice from the other room" section):
```
highpass=f=420:poles=2, lowpass=f=3000:poles=2,
acrusher=bits=7:mix=0.85:mode=log:dc=1:aa=0.35:samples=2,
acompressor=threshold=0.12:ratio=6:attack=5:release=120:makeup=2.2:knee=2,
aecho=0.9:0.2:23:0.35,
volume=1.8
```
(`lowpass=poles=2` is the 2-pole setting, 12 dB/oct; it is valid. Do **not** write
`bandpass=...:poles=2` — see the correction note in §4.1.)
`acrusher` real options (verified): `bits 1..64 (def 8)`, `mix 0..1 (def 0.5)`,
`mode lin|log (def lin)`, `dc 0.25..4 (def 1)`, `aa 0..1 (def 0.5)` (anti-aliasing),
`samples 1..250 (def 1)` (**this is the decimation knob** = your `coarse`),
`lfo`/`lforange 1..250`/`lforate 0.01..200`.
Note `samples=250` at 48 kHz = 192 Hz sample rate — extreme. `samples=6..20` is the useful
musical range for "dying digital".

**Tape**:
```
asetrate=44100*0.97,aresample=48000,atempo=1/0.97*1.0,
highpass=f=32,lowpass=f=13500:poles=2,
aecho=0.85:0.22:70|140:0.4|0.18,
vibrato=f=0.55:d=0.06,
asoftclip=type=tanh:param=0.8:oversample=2,
alimiter=limit=0.94:attack=8:release=140
```
`vibrato=f=0.55:d=0.06` = a 0.55 Hz ±6 % pitch wobble — **that is your wow/flutter in one
filter**. (`vibrato` modulates delay hence pitch; `tremolo` mods amplitude:
`tremolo=f=6.5:d=0.25` = 6.5 Hz flutter.) Note `asetrate` changes both pitch and duration,
so pair with `atempo` if length must be preserved.

**Noise floor / "something is recording this"**:
```
highpass=f=55, lowpass=f=9500,
tremolo=f=0.31:d=0.08,
aecho=0.7:0.3:2400:0.25,
acompressor=threshold=0.2:ratio=2:attack=80:release=800
```
A 2400 ms single echo at 25 % is a "big empty room next door"; combine with
`apulsator=...:ms=2400` for a stereo version.

**Reversal / pre-echo** (for the crash *before* the crash):
```
areverse, adelay=delays=120:all=1, areverse
```
Reversing, delaying, reversing again produces a **pre-echo that swells into the
transient** — the classic horror stinger. `adelay=delays=120:all=1` delays all channels by
120 ms. Use 80–400 ms. Do it on a *copy* of the mix and `amix`, not on the master, or you
lose the first 120 ms of everything.

**Stutter / gate by ffmpeg** (if you'd rather do the stutter offline):
```
# 18 Hz square gate, 100% depth
tremolo=f=18:d=1
# or a hard on/off via aeval, 60 ms on / 40 ms off:
aeval=val(0)*lt(mod(t\,0.1)\,0.06)
```
`aeval` is present; the expression language has `val(ch)`, `t`, `mod`, `lt`, `gt`, `if`.
`aeval` is per-sample and slow, but it is the only way to do sample-exact offline gating.
For real-time use your Python gate (§2.9) instead.

**Crossfade two glitch takes**:
```
[0:a][1:a]acrossfade=d=1.5:c1=tri:c2=tri
```
`acrossfade` takes 2 inputs. `d` in seconds, `c1`/`c2` curve (`tri`, `qsin`, `hsin`,
`exp`, `log`, `par`, `quad`, `cub`, `squ`, `cbr`). For a horror montage, `c1=exp:c2=log`
gives an audible "suck then slam" rather than a neutral dissolve.

**Mixing a dry and a processed path** (the single most useful ffmpeg idiom here):
```
-filter_complex "[0:a]asplit=2[dry][wet];[wet]highpass=f=400,acrusher=bits=6:samples=4,volume=0.8[wd];[dry][wd]amix=inputs=2:weights=1 0.6:normalize=0"
```
`amix` `weights` and `normalize=0` are what let you A/B a processed copy against the dry
without the automatic −6 dB per input. **Always set `normalize=0`.**

### 4.4 What to run offline vs. what stays in Python

| Task | Do it where | Why |
| --- | --- | --- |
| Bed generation, glitch processing, duck, gate, ring mod | **Python (real-time)** | must respond to terminal events |
| Waveshaping with oversampling (`asoftclip ... oversample=4`) | **ffmpeg** | naive Python clip aliases audibly; ffmpeg's is clean |
| Reverb (IR/convolution), `loudnorm`, final limiting | **ffmpeg** | cheap and correct off-line |
| `rubberband` pitch/formant work, `areverse` pre-echo | **ffmpeg** | stdlib Python can't do these well |
| Wow/flutter, tape band-limit, radio band-limit | **ffmpeg** | one-liners, no state to maintain |

If you need it *live*: run one ffmpeg as a **persistent filter process** in the pipe chain
(`python -c ... | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 -af "<chain>" -f s16le -ar 48000 -ac 2 pipe:1 | ffplay ...`)
and keep the real-time effects (`tremolo`, `aphaser`, `stereowiden`, `asoftclip`,
`acompressor`, `alimiter`) in that chain — they are all streaming-safe. Do **not** put
`loudnorm`, `areverse`, `rubberband`, or `afir` in the live path: `loudnorm` and `areverse`
need the whole file, and `rubberband`'s latency will drift out of sync with your terminal.

---

## 5. What NOT to do

Drawn from what the project explicitly forbids and from what will read as "cheap" in a
horror crash demo.

**5.1 Do not use randomness.** The project bans `rand`, `sometimes`, `perlin`, `choose`,
`degrade`, and the mini `|` operator (`docs/mini-syntax.md:25-31`: *"`|` is a random-choice
operator… it directly violates this project's zero-randomness principle"*). Randomly
jittering glitch amplitudes/timings is precisely what makes cheap glitch packs sound
cheap — your ear hears "uniform distribution" and stops believing the machine is broken.
Use fixed stepping lists (`[.02 .05 .02 .07 .03 .02 .09 .04]`) and prime-number intervals.
If you genuinely need per-glitch variation, seed a `random.Random(fixed_seed)` and step it
by a prime count — deterministic, but not obviously periodic.

**5.2 Do not `.fast(n)` a control on a sustained sound.** `docs/mini-syntax.md:66-71`:
segmented control values inside one cycle **split sustained notes** (measured: panA events
went 196 → 205). In your mixer this is the "zipper noise / clicks at LFO boundaries"
failure. Every continuous modulation must be either a single slow cycle
(`sine.range(a,b).slow(n)`, "one segment per cycle ⇒ no internal boundary") or a scalar.
Corollary: **never step a filter cutoff or gain without a 2–10 ms ramp.**

**5.3 Do not lean on `shape()` at the project's values.** `.shape(0.15)` and `.shape(.18)`
produce `k ≈ 0.35` — barely-there saturation, which is exactly the "flat" you are hearing
if you copied it. The project uses it as *midrange bite on a bass*, not as distortion.
For a horror glitch you want `shape 0.6–0.95` (`k = 3 → 38`) or the `distort` control with
`distorttype` 4/5/6/7 (`diode`/`asym`/`fold`/`sinefold`).

**5.4 Do not stack raw voices as a substitute for processing.** `docs/TERMINAL-SCORE.md:201`
records the project's own conclusion about why its browser playback crackles: *"9–13 sample
layers open at once plus `room/delay` reverb — the Web Audio thread isn't saturated but the
worklet buffer underruns and it pops."* In your Python mixer the equivalent failure is
summing many one-shot glitch voices and clipping the result. One noise bus + a small voice
pool + a limiter, not 20 simultaneous one-shots.

**5.5 Do not chase the project's "one piano, no FX" aesthetic.** `docs/mini-syntax.md:96-102`
(conclusions from the Rolling Girl transcription) says beautiful-sounding arranging comes
from *non-grid durations + unequal phrase lengths + variation on repeat + voices yielding to
each other + drums that morph*, and **explicitly** that *"emotion is all in the notes;
timbre is restrained… our piling on FX actually diluted the expression."* That is correct
for a piano piece and **exactly wrong for an analog-horror crash demo**, where the timbre
*is* the content. Take the discipline (determinism, contrast by vacuum, long releases) and
ignore the asceticism.

**5.6 Do not build on `sizzle`, `z_noise`, or `s("hh")`.** `sizzle` is in your docs'
synth-name dump but is **not** in the SuperDough 1.2.6 noise registry (registered noise
synths: `pink white brown crackle` only), and `z_noise`/`zt_*`/`zzfx` are zzfx-generated
variants, not filters. `s("hh")` is a **sampled hi-hat from the Dirt-Samples library**
(`docs/sounds/drum-machines.md` lists `hh(5)`, `9000_hh(1)`, `akaixr10_hh(2)`…), i.e. a
decaying metallic sample — it is not a noise generator and cannot be "processed" the way
you need. Generate your own noise; do not depend on a sample pack that may not be present.

**5.7 Do not use `legato()` as a synthesis control.** `docs/mini-syntax.md:73-77`: *"legato()
is invisible on the Node side — `legato(.5)` and `legato(2)` produce identical part/whole
boundaries."* The project's conclusion: *"the only two guarantees are long `release` and
voice overlap."* If you want overlap, extend the release.

**5.8 Do not use `portamento`.** `docs/mini-syntax.md:87`: it does not exist in Strudel 1.x
(commented out in `controls.mjs`), and it is *"the only runtime crash this project ever
had"* — static validation cannot catch it. For your glitch pitch slides, implement it
yourself by ramping the playback rate (§2.10), not by expecting a glide control.

**5.9 Do not use `lpf` on a `0` value expecting silence in a mixer.** In Strudel `lpf(0)`
is a closed filter used as a *musical* gate symbol (`shattered_mirror.strudel:105,108`
etc.). A real biquad at 0 Hz will produce DC and denormals, not silence. If you want
silence, ramp the gain — and add a DC blocker.

**5.10 Do not put `loudnorm`/`areverse`/`rubberband` in the live pipe.** They need the whole
stream (or add latency), and your ffplay sync will drift. Keep the live ffmpeg to
streaming-safe filters only (§4.4).

**5.11 Do not band-limit only at the top.** Analog horror reads as *analog* because of the
combination of a **low** band-limit (25–55 Hz high-pass — no subsonic, which is what real
tape/radio does) and a **gradual high** roll-off (4–6 dB/oct from ~4–6 kHz upward, not a
brick wall at 16 kHz). A clean 20 Hz–20 kHz response sounds "digital hifi" and is the
single most common reason a glitch library feels flat. §4.1's `firequalizer` (measured
−4.1 dB at 8 kHz, −15 dB at 20 kHz) is there precisely for this.

**5.12 Do not reach for `bandpass` expecting a band.** Measured on this build it is a
one-pole HP + one-pole LP with ~6 dB/octave skirts, and it rejects the passband edges far
too gently to serve as a band-limit; it also has no `poles` option, so `bandpass=...:poles=N`
is a **hard ffmpeg error**, not a silent fallback. Use `firequalizer`, `asupercut`/
`asuperpass`, or an explicit `highpass`+`lowpass` pair.

---

## 6. Quick-start order of work

1. Implement §2.1 (four noise gens, exact coefficients) + §2.12 DC blocker. Verify by
   measuring spectral slope: brown ≈ −6 dB/oct, pink ≈ −3, white ≈ 0.
2. Implement §2.2 SVF + §2.3 resonator + §2.4 ramps. This is 80 lines and is the whole
   "texture" problem.
3. Build the bed exactly as §3.4 with the five slow LFOs. Listen for 10 minutes. If it
   is boring, do **not** add layers — shorten the LFO periods and widen the gain LFO.
4. Implement §2.5 (pick `soft`, `diode`, `fold` — skip the rest), §2.6 crush/coarse,
   §2.9 ring/AM, §2.8 comb.
5. Implement the five glitches (§3.3) as keyframe tables. Verify each against its
   "sounds like" line. Tune `bp_center`/`comb_delay` before touching anything else.
6. Add the duck (§3.1 rule 2). Then add the fake-stop (cut everything to −∞ for 300–800 ms,
   per §1.9 rule 3) on the crash.
7. Batch-render one 60 s take to WAV and run §4.1. Compare A/B. Adjust `acompressor`
   threshold and the `bandpass` centre last.
8. Only then consider live ffmpeg in the pipe, with the §4.4 streaming-safe subset.
