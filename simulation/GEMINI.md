# Simulation Context — Algorithm Prototyping

## Purpose
This folder is for **pure Python prototyping** of beamforming and DOA algorithms
before they get integrated into the live software. No GUI, no hardware dependency.
Input: simulated or recorded numpy arrays. Output: DOA estimates, heatmaps, plots.

## What Lives Here
- Beamforming algorithm implementations (MVDR, MUSIC, Delay-and-Sum)
- Simulated microphone array signal generation (for testing)
- Algorithm benchmarking and accuracy evaluation
- Visualization scripts using matplotlib (OK here — not real-time)

## Array Geometry
- **Linear or planar array** of 8 microphones
- Spacing: half-wavelength at target frequency (default ~343Hz / 2f)
- Coordinate system: mic positions in meters, stored as `np.ndarray` shape `(8, 2)` for 2D or `(8, 3)` for 3D

## Key Algorithm Patterns

### Delay-and-Sum (DAS)
```python
# steering_vector shape: (n_mics,) complex
# data shape: (n_mics, n_samples)
output = np.abs(steering_vector.conj() @ data) ** 2
```

### MVDR (Capon)
```python
R = (data @ data.conj().T) / n_samples  # covariance matrix (n_mics, n_mics)
R_inv = np.linalg.inv(R + diagonal_loading * np.eye(n_mics))
power = 1.0 / (v.conj() @ R_inv @ v).real  # v = steering vector
```

### MUSIC
```python
eigenvalues, eigenvectors = np.linalg.eigh(R)
noise_subspace = eigenvectors[:, :n_mics - n_sources]
pseudo_spectrum = 1.0 / np.abs(v.conj() @ noise_subspace @ noise_subspace.conj().T @ v)
```

## Conventions
- All audio data arrays: shape `(n_channels, n_samples)`, dtype `np.float32`
- Covariance matrices: shape `(n_channels, n_channels)`, dtype `np.complex64`
- Steering vectors: shape `(n_channels,)`, dtype `np.complex128`
- Angles: always in **degrees** at the API level, convert to radians internally
- Heatmap output: shape `(n_elevation, n_azimuth)`, dtype `np.float32`, normalized 0–1

## Dependencies
```
numpy
scipy
matplotlib   # OK in simulation only
```

## Gemini Should Help With
- Implementing steering vector computation for arbitrary array geometries
- Adding diagonal loading to ill-conditioned covariance matrices
- Generating synthetic test signals (plane waves from known DOA + noise)
- Converting 1D DOA sweep to 2D azimuth/elevation heatmap grid
- Benchmarking MVDR vs MUSIC accuracy vs SNR