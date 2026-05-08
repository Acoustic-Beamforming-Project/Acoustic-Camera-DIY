
# from scipy.fft import fft, fftfreq, fftshift, ifft, ifftshift
# import numpy as np
# import matplotlib.pyplot as plt

# c = 343
# f = 4000

# lam = c / f
# d = lam / 2
# k = 2 * np.pi / lam

# # ARRAY GEOMETRY
# Ncx = 6
# Ncy = 6
# micx = np.arange(12) - Ncx + 1
# micy = np.arange(12) - Ncy + 1
# micx, micy = np.meshgrid(micx, micy)
# # Flatten sensors
# micx = micx.flatten()
# micy = micy.flatten()

# # ANGLE GRID
# theta = np.linspace(0, np.pi, 300)
# phi   = np.linspace(0, np.pi, 300)
# theta, phi = np.meshgrid(theta, phi)

# # Flatten angle grid
# theta_flat = theta.flatten()
# phi_flat = phi.flatten()

# # STEERING MATRIX

# V = np.exp(
#     -1j * k * d *
#     (
#         micx[:, None] * np.cos(theta_flat)[None, :] +
#         micy[:, None] * np.cos(phi_flat)[None, :]
#     )
# )

# # BEAM STEERING DIRECTION

# theta0 = np.deg2rad(90)
# phi0 = np.deg2rad(60)

# W = np.exp(
#     -1j * k * d *
#     (
#         micx * np.cos(theta0) +
#         micy * np.cos(phi0)
#     )
# )

# # CONVENTIONAL BEAMFORMER

# B = np.abs(W.conj() @ V) ** 2

# # reshape back to angle grid
# B = B.reshape(theta.shape)

# B_norm = B / np.max(B)

# R = B_norm 

# X = R * np.cos(theta) 
# Y = R * np.cos(phi)
# Z = R * np.sin(theta) * np.sin(phi)
# # ux = np.cos(theta)
# # uy = np.cos(phi)

# # valid = ux**2 + uy**2 <= 1

# # uz = np.zeros_like(ux)
# # uz[valid] = np.sqrt(1 - ux[valid]**2 - uy[valid]**2)

# # X = R * ux
# # Y = R * uy
# # Z = R * uz

# # PLOT

# fig = plt.figure(figsize=(10, 8))
# ax = fig.add_subplot(111, projection='3d')
# ax.set_xlim(0,np.pi)
# ax.set_ylim(0,np.pi)
# surf = ax.plot_surface(
#     theta,
#     phi,
#     B,
#     cmap='jet',
#     linewidth=0,
#     antialiased=True
# )

# plt.show()


from scipy.fft import fft, fftfreq, fftshift, ifft, ifftshift
import numpy as np
import matplotlib.pyplot as plt

c = 343
f = 4000

lam = c / f
d = lam / 2
k = 2 * np.pi / lam

# ARRAY GEOMETRY
Ncx = 6
Ncy = 6
micx = np.arange(12) - Ncx + 1
micy = np.arange(12) - Ncy + 1
micx, micy = np.meshgrid(micx, micy)
# Flatten sensors
micx = micx.flatten()
micy = micy.flatten()

# ANGLE GRID
theta = np.linspace(0, np.pi, 300)
phi   = np.linspace(0, np.pi, 300)
theta, phi = np.meshgrid(theta, phi)


# Flatten angle grid
theta_flat = theta.flatten()
phi_flat = phi.flatten()


# steering grid 
steer_theta = np.linspace(np.deg2rad(45), np.deg2rad(135), 2)
steer_phi   = np.linspace(np.deg2rad(45), np.deg2rad(135), 2)
steer_theta, steer_phi = np.meshgrid(steer_theta, steer_phi)

# Flatten angle grid
steer_theta_flat = steer_theta.flatten()
steer_phi_flat = steer_phi.flatten()


# STEERING MATRIX

V = np.exp(
    -1j * k * d *
    (
        micx[:, None] * np.cos(theta_flat)[None, :] +
        micy[:, None] * np.cos(phi_flat)[None, :]
    )
)

# BEAM STEERING DIRECTION

theta0 = np.deg2rad(90)
phi0 = np.deg2rad(60)

W = np.exp(
    -1j * k * d *
    (
        micx[:, None] * np.cos(steer_theta_flat)[None, :] +
        micy[:, None] * np.cos(steer_phi_flat)[None, :]
    )
)

# CONVENTIONAL BEAMFORMER

B_raw = np.abs(W.conj().T @ V)**2

# 2. RESHAPE TO: (Number of Beams, Theta Res, Phi Res)
# This maps each of the 25 beams to the 300x300 plotting grid
B = B_raw.reshape(len(steer_theta_flat), theta.shape[0], theta.shape[1])

fig = plt.figure(figsize=(10, 8))
# ax = fig.add_subplot(111, projection='3d')
ax2 = fig.add_subplot(111, projection='3d')
#  3. LOOP THROUGH EACH STEERED BEAM
for i in range(B.shape[0]):
    Bi = B[i] 
    R = Bi / np.max(Bi)
    
    X = R * np.cos(theta) 
    Y = R * np.cos(phi)
    Z = R * np.sin(theta) * np.sin(phi)
    
    # ax.plot_surface(
    #     X, Y, Z,
    #     cmap='jet',
    #     linewidth=0,
    #     antialiased=True,
    #     alpha=0.6
    # )
    
    ax2.plot_surface(
        theta,phi,Bi,
        cmap='jet',
        linewidth=0,
        antialiased=False,
        alpha=0.6)

# ax.set_xlim(-1,1)
# ax.set_ylim(-1,1)

ax2.set_xlim(0,np.pi)
ax2.set_ylim(0,np.pi)

# ax.set_title(f"Radiation Patterns for {len(steer_theta_flat)} Beams")
# ax.set_xlabel('X')
# ax.set_ylabel('Y')
# ax.set_zlabel('Z')
plt.show()
# 
# # 3. LOOP THROUGH EACH STEERED BEAM
# for i in range(B.shape[0]):
#     # Get the 2D response for the i-th steering direction
#     Bi = B[i] 
    
#     # Normalize current beam so it fits in the plot (0 to 1 range)
#     R = Bi / np.max(Bi)
    
#     # Convert to Spherical-style Coordinates for 3D plotting
#     # Note: Using your logic for X, Y, Z mapping
#     X = R * np.cos(theta) 
#     Y = R * np.cos(phi)
#     Z = R * np.sin(theta) * np.sin(phi)
    
#     surf = ax.plot_surface(
#         X, Y, Z,
#         cmap='jet',
#         linewidth=0,
#         antialiased=True,
#         alpha=0.6 # Added transparency to see overlapping beams
#     )

# ax.set_title(f"Radiation Patterns for {len(steer_theta_flat)} Beams")
# ax.set_xlabel('X')
# ax.set_ylabel('Y')
# ax.set_zlabel('Z')
# ax.set_xlim(-1,1)
# ax.set_ylim(-1,1)
# plt.show()