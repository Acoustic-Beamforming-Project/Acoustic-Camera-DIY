// ─────────────────────────────────────────────────────────────────────────────
//  Wideband Beamforming — Math and Code, Side by Side
//  A personal study guide for replacing dsp_worker.py
// ─────────────────────────────────────────────────────────────────────────────

#set page(paper: "a4", margin: (x: 2.2cm, y: 2.2cm))
#set text(font: "Linux Libertine", size: 11pt, lang: "en")
#set heading(numbering: "1.1")
#set par(justify: true, leading: 0.75em)

#show raw: set text(font: "Courier New", size: 9.5pt)
#show raw.where(block: true): block.with(
  fill: rgb("#f4f4f4"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
)
#show heading.where(level: 1): it => {
  v(1.2em)
  text(size: 15pt, weight: "bold", fill: rgb("#1a1a2e"))[#it]
  v(0.4em)
}
#show heading.where(level: 2): it => {
  v(0.8em)
  text(size: 12.5pt, weight: "bold", fill: rgb("#16213e"))[#it]
  v(0.3em)
}

// Coloured callout box
#let note(body) = block(
  fill: rgb("#e8f4f8"),
  stroke: 1pt + rgb("#2980b9"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
)[#body]

#let warn(body) = block(
  fill: rgb("#fff3cd"),
  stroke: 1pt + rgb("#f0ad4e"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
)[#body]

#let insight(title, body) = block(
  fill: rgb("#eaf7ea"),
  stroke: 1pt + rgb("#27ae60"),
  inset: 10pt,
  radius: 4pt,
  width: 100%,
)[*#title* #body]

// ─────────────────────────────────────────────────────────────────────────────

#align(center)[
  #v(0.5cm)
  #text(size: 22pt, weight: "bold", fill: rgb("#1a1a2e"))[
    Wideband Beamforming
  ] \
  #v(0.2cm)
  #text(size: 13pt, style: "italic", fill: rgb("#555555"))[
    Every line of the notebook explained — math first, then the code that does it
  ]
  #v(0.5cm)
  #line(length: 100%, stroke: 1pt + rgb("#cccccc"))
]

#v(0.5cm)
#outline(depth: 2, indent: 1em)
#pagebreak()

// ─────────────────────────────────────────────────────────────────────────────
= Why You Are Replacing `dsp_worker.py`
// ─────────────────────────────────────────────────────────────────────────────

Your current `_srp_phat()` function has a loop that runs 120 times (once per mic pair), and inside that loop there is *another* Python loop over all 181 angles. This is slow because Python executes each iteration one at a time.

The notebook replaces both loops with a single matrix multiply. Before we can understand the matrix, we need to understand what it contains, which means we need to understand how a time delay becomes a complex number. That is the entire first half of this document.

#note[
  *Reading plan.* Sections 2–4 are pure math — read them slowly and do not skip them. Section 5 is where the notebook's actual code is explained line by line. Section 6 shows the exact changes to your `dsp_worker.py`.
]

// ─────────────────────────────────────────────────────────────────────────────
= The Physics: How Sound Arrives Late
// ─────────────────────────────────────────────────────────────────────────────

== Geometry of a microphone array

You have 16 microphones on a line, spaced $d = 0.05$ m apart. A sound source is far away at angle $theta$ measured from the broadside (perpendicular to the array).

When sound arrives from angle $theta$, the wavefront hits each microphone at a slightly different time. Microphone $n$ (counting from the centre) is at position $x_n = n dot d$ metres from the centre. The extra distance the wave must travel to reach mic $n$ compared to the centre is:

$ Delta x_n = n dot d dot sin(theta) $

The time it takes sound to travel that extra distance is the *Time Difference of Arrival* (TDOA):

$ tau_n (theta) = frac(n dot d dot sin(theta), c) $

where $c = 343$ m/s. So mic $n$ hears the sound $tau_n$ seconds *after* the centre mic (if the sound comes from the positive side).

#note[
  *Concrete example.* $d = 0.05$ m, $theta = 30°$, $n = 7$ (the rightmost mic):
  $tau_7 = 7 times 0.05 times sin(30°) / 343 = 7 times 0.05 times 0.5 / 343 approx 0.00051$ seconds $approx 24$ samples at 48 kHz.

  In your old code, this 24.5 gets rounded to 24 — you lose the 0.5 sample. In the new code, you keep it exactly.
]

== The angular convention in the notebook

The notebook uses $theta in [0°, 180°]$ with $cos(theta)$ instead of $sin(theta)$. This is the *axial convention*: $theta = 90°$ means broadside (straight ahead), $theta = 0°$ means end-fire left, $theta = 180°$ means end-fire right.

Your `config.py` uses $theta in [-90°, +90°]$ with $sin(theta)$: $theta = 0°$ is broadside. These describe the same physical directions — just different coordinate choices.

$ underbrace(sin(theta_"your"), theta in [-90, 90]) = underbrace(cos(theta_"notebook"), theta_"notebook" in [0, 180]) $

The `dsp_worker.py` replacement at the end of this document uses the $sin$ convention to stay consistent with your existing `SCAN_ANGLES` and display code.

// ─────────────────────────────────────────────────────────────────────────────
= The Key Insight: A Delay Is a Phase Rotation
// ─────────────────────────────────────────────────────────────────────────────

This is the single idea that makes the whole notebook work. Read this section until it is obvious.

== A pure tone in the time and frequency domain

Consider a single tone at frequency $f$:

$ s(t) = cos(2 pi f t) $

Using Euler's formula, we can write this as the real part of a complex exponential:

$ s(t) = "Re"[e^(j 2 pi f t)] $

The Fourier transform of $s(t)$ at frequency $f$ gives us a complex number $S(f)$. Its magnitude tells us *how loud* that frequency is. Its *angle* (phase) tells us *where in the cycle* we are at time $t = 0$.

== What happens when you delay the signal

Now delay the same tone by $tau$ seconds — this is what the microphone array does physically:

$ s(t - tau) = cos(2 pi f (t - tau)) = "Re"[e^(j 2 pi f (t - tau))] $

Expanding:

$ e^(j 2 pi f (t - tau)) = e^(j 2 pi f t) dot e^(-j 2 pi f tau) $

The second factor $e^(-j 2 pi f tau)$ does not depend on time. In the Fourier domain this means:

#align(center)[
  #block(
    fill: rgb("#1a1a2e"),
    inset: 12pt,
    radius: 4pt,
  )[
    #text(fill: white, size: 12pt)[
      $S_"delayed"(f) = S(f) dot e^(-j 2 pi f tau)$
    ]
  ]
]

*A time delay $tau$ in the time domain is exactly multiplication by $e^(-j 2 pi f tau)$ in the frequency domain.* This is not an approximation. It is exact for any signal and any delay, including non-integer sample delays.

== Corollary: phase of $X(f)$ is timing information

*Claim:* The phase angle $phi = angle X(f)$ of the Fourier transform of a signal is directly proportional to the time delay at which that frequency component arrived.

*Proof:*

Let a signal $s(t) = e^(j 2 pi f_0 t)$ be delayed by $tau$ seconds: $s(t - tau)$.

Its Fourier transform at $f_0$ is:

$ X(f_0) = integral_(- infinity)^(infinity) e^(j 2 pi f_0 (t - tau)) e^(-j 2 pi f_0 t) d t = e^(-j 2 pi f_0 tau) $

The phase of this is:

$ angle X(f_0) = -2 pi f_0 tau $

Therefore:

$ tau = - frac(angle X(f_0), 2 pi f_0) $

*The phase at each frequency is a direct measurement of the delay.* $square$

#insight("Why this matters for your array:")[
  Each microphone receives the same signal delayed by a different $tau_n$. In the frequency domain, mic $n$'s signal at frequency $f$ is just the source signal multiplied by $e^(-j 2 pi f tau_n)$. The steering matrix $bold(W)$ is a table of those exact complex numbers, pre-computed for every combination of mic, frequency, and candidate angle.
]

// ─────────────────────────────────────────────────────────────────────────────
= The Steering Matrix
// ─────────────────────────────────────────────────────────────────────────────

== Building it up from what we know

We know the delay for mic $n$ at angle $theta$ and frequency $f$ is:

$ tau_n(theta) = frac(n dot d dot sin(theta), c) $

So the complex number that represents "mic $n$'s delay at angle $theta$ and frequency $f$" is:

$ W_(f, n, theta) = e^(-j 2 pi f tau_n(theta)) = e^(-j 2 pi f dot frac(n dot d dot sin(theta), c)) $

Substituting the *wavenumber* $k = 2 pi f / c$:

$ W_(f, n, theta) = e^(-j dot k(f) dot d dot n dot sin(theta)) $

The full steering matrix $bold(W)$ is just this formula evaluated for every $(f, n, theta)$ simultaneously. It has shape (frequencies × mics × angles).

== The notebook's code for this

```python
# From notebook cell 4 (the wideband version your team used):

Nc = 8                                          # centre mic index
c  = 343
d  = (c / 4000) / 2                             # half-wavelength at 4000 Hz

# k is an array of wavenumbers, one per frequency bin
# shape: (100,)
k = 2 * np.pi / c * np.linspace(1000, 4001, 100)

mic = np.arange(1, 16) - Nc                     # mic indices: [-7, -6, ..., 7]
                                                 # shape: (15,)

steering_angles = np.deg2rad(np.linspace(0, 180, 100))
                                                 # shape: (100,)

# THE STEERING MATRIX
# shape: (100 freqs, 15 mics, 100 angles)
W = np.exp(
    -1j * d * k[:, None, None]                  # (100,  1,   1  )
             * mic[None, :, None]               # (  1,  15,  1  )
             * np.cos(steering_angles[None, None, :])  # (1, 1, 100)
)
```

== What `[:, None, None]` does — broadcasting

NumPy broadcasting lets you multiply arrays of different shapes as long as their dimensions are compatible. The trick is to add size-1 dimensions with `None` (same as `np.newaxis`) so NumPy knows which axis to align.

Without broadcasting you would need three nested loops:

```python
# Slow version with loops — equivalent to the one line above
W = np.zeros((100, 15, 100), dtype=complex)
for f_idx in range(100):           # loop over frequencies
    for n in range(15):            # loop over mics
        for a_idx in range(100):   # loop over angles
            W[f_idx, n, a_idx] = np.exp(
                -1j * d * k[f_idx] * mic[n] * np.cos(steering_angles[a_idx])
            )
```

Broadcasting does all 100 × 15 × 100 = 150,000 multiplications in one C call. The shapes broadcast like this:

```
k[:, None, None]                →  (100,   1,   1)
mic[None, :, None]              →  (  1,  15,   1)
cos(angles)[None, None, :]      →  (  1,   1, 100)
─────────────────────────────────────────────────
product                         →  (100,  15, 100)   ← W shape
```

// ─────────────────────────────────────────────────────────────────────────────
= The Beamforming Step: `einsum`
// ─────────────────────────────────────────────────────────────────────────────

== What we want to compute

We have the steering matrix $bold(W)$ of shape (F freqs, M mics, A angles). We have the measured signal $bold(X)$ of shape (F freqs, M mics) — the FFT of each microphone's recording at each frequency.

For each candidate angle $theta$, we want to compute the beamformed output: apply the conjugate of the steering weights to the signal and sum over all mics.

$ Y(f, theta) = sum_(n=0)^(M-1) W^*(f, n, theta) dot X(f, n) $

In matrix terms: for each frequency $f$, multiply the complex-conjugate of the $f$-th slice of $W$ by the corresponding signal, and sum over the mic axis.

== What `np.einsum` does

`np.einsum` is Einstein summation notation. You write a string that describes which axes to multiply and which to sum over, and NumPy handles the rest.

```python
Y = np.einsum('fms, fm -> fs', W.conj(), signal_aligned)
```

Read the string `'fms, fm -> fs'` as:

- First array has axes (f=freq, m=mic, s=steering angle) — this is `W.conj()`
- Second array has axes (f=freq, m=mic) — this is `signal_aligned`
- Output has axes (f=freq, s=steering angle) — this is `Y`
- The `m` axis appears in both inputs but *not* in the output — so NumPy sums over it

Expanded:

```
Y[f, s] = sum over m:  W.conj()[f, m, s]  *  signal[f, m]
```

This is exactly the formula above. One line instead of three nested loops.

== The PHAT whitening step

Before passing the signal into `einsum`, the notebook normalises each frequency bin to magnitude 1. This is the "PHAse Transform" part:

```python
# After FFT, before einsum:
Xf      = np.fft.rfft(data, axis=1)          # shape (N_CHANNELS, N_FFT//2+1)
Xf_phat = Xf / (np.abs(Xf) + 1e-10)          # divide by magnitude
```

`np.abs(Xf)` computes $|X(f)|$ — the magnitude (loudness) at each frequency. Dividing removes the magnitude, leaving only the phase. After this, every frequency bin has magnitude 1 and its phase intact.

*Why?* Without PHAT, strong frequencies dominate. A 4 kHz tone with amplitude 10 contributes 10× more to the beam power than a 1 kHz tone with amplitude 1. Their delays are equally informative for DOA estimation, so we do not want amplitude to matter. PHAT makes every frequency equally important for the timing (phase) information it carries.

== The wideband sum

```python
P = np.mean(np.abs(Y)**2, axis=0)   # shape: (n_angles,)
```

`np.abs(Y)**2` computes the power at each (frequency, angle). `np.mean(..., axis=0)` averages across the frequency axis, giving total power at each angle across the whole band. The angle with the highest power is the DOA estimate.

#note[
  *Summary of the full pipeline:*
  #v(0.2em)
  1. FFT each channel → $X(f, n)$
  2. PHAT-whiten → $hat(X)(f, n) = X(f,n) / |X(f,n)|$
  3. Extract the frequency bins matching your steering frequencies
  4. `einsum` → $Y(f, theta) = sum_n W^*(f,n,theta) dot hat(X)(f,n)$
  5. Average power → $P(theta) = "mean"_f |Y(f,theta)|^2$
  6. $hat(theta) = arg max_theta P(theta)$
]

// ─────────────────────────────────────────────────────────────────────────────
= The Phase-Delay Demo (Notebook Cell 2)
// ─────────────────────────────────────────────────────────────────────────────

This is the very first demo in the notebook. It proves the phase-equals-delay idea on a real signal before any array processing.

```python
N = 4800
T = 1 / 48000
t = np.arange(0.0, N*T, T)
S = np.sin(2*np.pi*4000*t) + np.sin(2*np.pi*3000*t)

tf = fftfreq(N, T)     # frequency axis in Hz
tf = fftshift(tf)      # shift so 0 Hz is in the centre
Sf = fft(S)            # complex spectrum
Sf = fftshift(Sf)      # shift to match tf

# Apply a delay of 0.0001 seconds (= 4.8 samples at 48 kHz)
# Multiply each frequency bin by e^(-j 2pi f tau)
Sf = Sf * np.exp(-1j * 2 * np.pi * tf * 0.0001)

# Convert back to time domain
S_sh = ifft(ifftshift(Sf))
```

*What each function does:*

- `fft(S)` — converts the N-sample time signal into N complex numbers, one per frequency. Same as `np.fft.fft`. Uses an O(N log N) algorithm.
- `fftfreq(N, T)` — builds the frequency axis: the $k$-th output of `fft` corresponds to frequency `fftfreq[k]` Hz.
- `fftshift(x)` — rearranges an FFT output so that zero frequency is in the middle instead of at index 0. Makes plots look natural (negative freqs on left, positive on right).
- `np.exp(-1j * 2 * np.pi * tf * 0.0001)` — this is the delay applied to every frequency at once. The shape of `tf` and `Sf` are both (N,), so this is element-wise: each frequency gets its own phase rotation.
- `ifftshift` undoes the shift before calling `ifft`, which converts back to time.

The plot shows `S` and `S_sh` overlaid — they look identical except `S_sh` is shifted right by 0.0001 seconds. This confirms: multiplying by $e^{-j 2\pi f  tau }$ in the frequency domain = shifting by $tau$ in the time domain.

// ─────────────────────────────────────────────────────────────────────────────
= The Frequency Bin Index Lookup
// ─────────────────────────────────────────────────────────────────────────────

This is the part that confused many people reading the notebook. In cell 4 there is this code:

```python
tf = fftshift(fftfreq(N, T))   # the frequency axis of the full FFT

# k holds 100 wavenumbers from 1000 to 4001 Hz (as radians/metre)
# We need to find which FFT bin corresponds to each of those frequencies.
# The wavenumber k = 2*pi*f/c, so the frequency in Hz is f = k*c/(2*pi)

idx_list = [
    np.argmin(np.abs(tf - (ki * c / (2 * np.pi))))
    for ki in k
]
signal_aligned = signal.T[idx_list, :]   # shape: (n_freqs, N_CHANNELS)
```

*Why is this needed?* The FFT gives you N bins — one for every integer multiple of the frequency resolution $Delta f = 1/(N dot T)$. Your steering matrix $bold(W)$ was built for 100 specific frequencies between 1000 and 4001 Hz. Those 100 frequencies do not land exactly on FFT bin centres. `np.argmin(np.abs(tf - target))` finds the nearest bin to each target frequency.

`signal.T` transposes from (N_CHANNELS, N_FFT) to (N_FFT, N_CHANNELS) so that indexing `[idx_list, :]` picks out the right frequency rows, giving shape (100 freqs, 16 mics) — matching what `einsum` expects.

#warn[
  *This is where your old code and the notebook diverge most.* Your old code used `np.fft.rfft` which only gives you positive frequencies (N//2+1 bins), and you used all of them. The notebook builds a steering matrix for a specific set of frequencies and selects those bins. The new `dsp_worker.py` uses `np.fft.rfft` (faster, since signals are real) and does the same bin selection.
]

// ─────────────────────────────────────────────────────────────────────────────
= Old Code vs New Code, Side by Side
// ─────────────────────────────────────────────────────────────────────────────

== The old inner loop (your current code)

```python
for i in range(N_CHANNELS):               # 16 iterations
    for j in range(i + 1, N_CHANNELS):    # up to 15 iterations = 120 total
        Xi   = np.fft.rfft(data[i])
        Xj   = np.fft.rfft(data[j])
        GCC  = Xi * np.conj(Xj)
        PHAT = GCC / (np.abs(GCC) + 1e-10)
        gcc_t = np.real(np.fft.irfft(PHAT))   # back to time domain

        for a_idx, tau in enumerate(delays):   # 181 iterations
            P[a_idx] += gcc_t[int(tau) % n_fft]   # integer index lookup
```

*What is slow:* 120 Python loop iterations, each calling `rfft` + `irfft`. 181 inner Python iterations per pair for the index lookup. Total: ~21,720 Python-level operations per frame.

*What loses accuracy:* `int(tau) % n_fft` — the delay is rounded to the nearest sample. At 48 kHz and 5 cm spacing, each sample represents about 7 mm of spatial resolution. Small angles near 0° have delays well under 1 sample and get rounded to 0.

== The new approach (steering matrix + einsum)

```python
# Done ONCE at startup — precompute W of shape (N_FREQS, N_CHANNELS, N_ANGLES)
W = np.exp(-1j * MIC_SPACING * k[:, None, None]
                              * mic[None, :, None]
                              * np.sin(angles)[None, None, :])

# Per frame — the entire DSP is these 5 lines:
Xf      = np.fft.rfft(data, axis=1)              # one call, all channels
Xf_phat = Xf / (np.abs(Xf) + 1e-10)             # PHAT whitening
sig     = Xf_phat[:, self._freq_idx].T           # select steering freqs
Y       = np.einsum('fma,fm->fa', self._W.conj(), sig)  # beamform
P       = np.mean(np.abs(Y)**2, axis=0)          # wideband power
```

*What is fast:* One `rfft` call for all channels. One `einsum` (internally a BLAS matrix multiply). Two element-wise operations. Zero Python loops.

*What is accurate:* The exponent `e^(-j k d n sin(theta))` is exact for any real-valued $theta$. There is no rounding.

// ─────────────────────────────────────────────────────────────────────────────
= One Last Thing: `W.conj()` — Why Conjugate?
// ─────────────────────────────────────────────────────────────────────────────

The steering vector $W_(f,n,theta) = e^{-j k d n sin(theta)}$ encodes the delay that sound *from* angle $theta$ *experiences* at mic $n$.

When we want to *steer the beam toward* $theta$ — i.e., ask "does the signal match what we would expect if the source were at $theta$?" — we need to *undo* those delays. Undoing a phase rotation of $-phi$ means applying $+phi$, which is the complex conjugate.

$ W^*(f, n, theta) = e^{+j k d n sin(theta)} $

Multiplying the received signal (which was delayed by $e^{-j k d n sin(theta)}$) by the conjugate steering weight cancels the delay:

$ e^{-j k d n sin(theta)} dot e^{+j k d n sin(theta)} = e^0 = 1 $

When the signals from all mics add up coherently (phases cancelled), you get a large $|Y|^2$. For all other angles, the phases do not cancel and they partially destructively interfere, giving smaller power.

#insight("The whole algorithm in one sentence:")[
  Build a matrix of complex numbers that represent the expected delays for every mic at every angle, take its conjugate (to undo those delays), multiply by the received signal, and the angle where everything lines up is your source direction.
]