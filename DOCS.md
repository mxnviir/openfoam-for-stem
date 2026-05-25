# Documentation

Reference guide for the OpenFOAM for STEM Racing platform. See [SETUP.md](SETUP.md) for initial installation and [README.md](README.md) for a usage overview.

---

## Table of Contents

1. [Changing the dashboard password](#1-changing-the-dashboard-password)
2. [Dashboard metrics explained](#2-dashboard-metrics-explained)
3. [OpenFOAM settings reference](#3-openfoam-settings-reference)
4. [Firebase reference](#4-firebase-reference)
5. [ParaView visualisation guide](#5-paraview-visualisation-guide)

---

## 1. Changing the dashboard password

The dashboard uses a single shared team password stored as a SHA-256 hash in Firestore. To change it:

**Step 1 — Generate the new hash**

```powershell
python -c "import hashlib; print(hashlib.sha256(b'YourNewPassword').hexdigest())"
```

Copy the 64-character output.

**Step 2 — Update Firestore**

1. [Firebase console](https://console.firebase.google.com) → your project → **Firestore Database**
2. Click the `_config` collection → `access` document
3. Click the pencil icon next to `passwordHash`
4. Paste the new 64-character hash → **Update**

The change takes effect immediately — no redeploy needed.

---

## 2. Dashboard metrics explained

### Drag (N)

Absolute aerodynamic drag force on the car in Newtons. This is averaged over the **last 100 iterations** of the fine mesh solve to smooth out solver noise. Lower is better for racing.

### Drag Δ (Drag Delta)

The change in drag force compared to the **immediately previous run** (ordered by submission time).

- **Green / negative** — drag decreased. Your change helped.
- **Red / positive** — drag increased. Your change made things worse.

The delta is purely informational — it compares whatever two runs happen to be adjacent in the table, so make sure you're comparing runs that only differ by one design change at a time.

### Lift (N)

Aerodynamic lift force in Newtons. **Negative = downforce, Positve = lift**. Not shown in the main table but available in the results CSV. Usually not worth enough optimising for.

### P Residual (Pressure Residual)

A measure of how well the simulation has converged. This is the final pressure (`p`) residual from the OpenFOAM solver log.

| Value | Interpretation |
|-------|---------------|
| `< 1e-4` | Well converged — drag and lift numbers are reliable |
| `1e-4` to `1e-3` | Acceptable — results are usable but treat with some caution |
| `> 1e-3` | Poorly converged — results are not reliable. Consider increasing `endTime` in `controlDict` or checking your geometry |

A high residual usually means one of: bad STL geometry, the solver needing more iterations, or a mesh quality issue.

### Process / Status

The `process` field tracks which stage the simulation is currently in:

| Value | What's happening |
|-------|-----------------|
| `queued` | Job submitted, waiting for a free EC2 instance |
| `coarse_mesh` | Running `blockMesh` + `snappyHexMesh` (no boundary layers) |
| `coarse_solving` | Running the coarse OpenFOAM solver (~500 iterations) |
| `fine_mesh` | Running `snappyHexMesh` again with boundary layers enabled |
| `mapFields` | Interpolating the coarse solution onto the fine mesh as a starting point |
| `fine_solving` | Running the fine OpenFOAM solver (~1500 iterations) |
| `done` | Complete — results available |
| `failed` | Something went wrong — check logs in Firebase Storage or SSH into the instance |
| `cancelled` | Cancelled via the dashboard cancel button |

---

## 3. OpenFOAM settings reference

All settings live in `openfoam_template/motorBike/system/`. The orchestrator copies this template for each job — changes to the template affect all future runs.

### `system/controlDict`

| Setting | Default | Effect |
|---------|---------|--------|
| `endTime` | `1500` | Number of iterations for the fine solve. Increase if p residual is not converging. Each 100 iterations adds ~3–4 minutes on a c7i.2xlarge. |
| `writeInterval` | `100` | How often OpenFOAM writes a full solution snapshot to disk. Lower values use more disk space but give finer-grained restart points. |
| `lRef` | `0.220` | Characteristic length (wheelbase) in metres. Used for Reynolds number calculation. |
| `CofR` | `(0.101 0 0.021)` | Centre of rotation for moment calculations. Roughly the centre of the car. |

Wind speed is set in `0/U` — the `internalField` and `inlet` boundary condition are both `(20 0 0)` by default (20 m/s in the X direction).

### `system/snappyHexMeshDict`

| Setting | Default | Effect |
|---------|---------|--------|
| `refinementLevel` (surfaces) | `(4 5)` | Min/max refinement levels applied at the car surface. Higher = finer surface mesh, slower meshing. |
| `nSurfaceLayers` | `3` | Number of boundary layer cells grown from the car surface (fine run only). More layers = better near-wall resolution, longer meshing. |

**Refinement boxes**

Three nested boxes control how densely the mesh is refined in different regions around the car. All coordinates are in metres, matching the domain axes (X = flow direction, Y = lateral, Z = vertical).

| Box | Default min | Default max | Purpose |
|-----|------------|------------|---------|
| `refinementBoxHigh` | `(−0.005, −0.045, 0.000)` | `(0.215, 0.003, 0.055)` | Tightest refinement — wraps closely around the car body. Should match your car's bounding box. |
| `refinementBoxMid` | `(−0.020, −0.055, 0.000)` | `(0.230, 0.005, 0.060)` | Medium refinement — roughly 1.5× the car in all directions. |
| `refinementBoxWake` | `(−0.020, −0.055, 0.000)` | `(0.500, 0.005, 0.065)` | Coarsest of the three — extends well downstream to capture the wake behind the car. |

If your car is a different size or position from the template, reposition these boxes to match:
- `refinementBoxHigh` should tightly surround your car (nose to tail, wheel to wheel, floor to roof)
- `refinementBoxMid` should be slightly larger in all directions (~1.5× car size)
- `refinementBoxWake` should extend **behind** the car by 2–3× the car length in the +X direction

Also check that `locationInMesh` (default `(0.500 −0.085 0.060)`) stays **inside the domain and outside your car body**. If your car extends past X = 0.5, move this point further downstream.

### `system/blockMeshDict`

Defines the outer wind tunnel domain. Default dimensions:

| Boundary | Position |
|----------|----------|
| Inlet (X−) | −0.339 m |
| Outlet (X+) | 0.871 m |
| Symmetry plane (Y+) | 0 m |
| Side wall (Y−) | −0.170 m |
| Ground (Z−) | −0.0003 m |
| Top (Z+) | 0.213 m |

Resize this if your car does not fit comfortably — see SETUP.md §5d.5 for clearance rules.

### Turbulence model

k-ω SST (`kOmegaSST`) is used for all runs. This is an industry-standard model for external aerodynamics with separation — it handles the car wake and wheel arches reasonably well at STEM car scales.

---

## 4. Firebase reference

### Firestore collections

#### `jobs` collection

One document per simulation run. Document ID = job name (e.g. `raven_pvsp_run_01`).

| Field | Type | Description |
|-------|------|-------------|
| `job_name` | string | Name of the run — matches the STL export folder name |
| `status` | string | Overall job status — see Process / Status table above |
| `process` | string | Current pipeline stage — see Process / Status table above |
| `created_at` | string | ISO 8601 UTC timestamp when the job was submitted from your Windows machine (e.g. `2026-04-02T12:54:00Z`) |
| `started_at` | string | ISO 8601 UTC timestamp when the EC2 instance was claimed and started |
| `instance` | string | Name of the EC2 instance that ran (or is running) the job, e.g. `cfd-2`. Keep note of this — you'll need it for the ParaView guide below. |
| `drag_N` | number | Drag force in Newtons — averaged over the last 100 fine-mesh iterations. `0.0` while the job is still running. |
| `lift_N` | number | Lift force in Newtons. Negative = downforce. `0.0` while running. |
| `p_residual` | number | Final pressure residual from the fine solver log. `0.0` while running. |
| `iteration` | number | Live solver iteration count — updates every ~10 seconds while solving |
| `iter_time` | number | Rolling average seconds-per-iteration over the last 10 iterations |
| `results_url` | string | Firebase Storage download URL for `results.csv` — populated when job reaches `done` |
| `stl_url` | string | Firebase Storage download URL for `car_body.stl` (the geometry used for this run) — populated when job reaches `done` |

#### `_config` collection

| Document | Field | Type | Description |
|----------|-------|------|-------------|
| `access` | `passwordHash` | string | SHA-256 hash of the dashboard password. See [section 1](#1-changing-the-dashboard-password) to update it. |

### Firebase Storage structure

```
jobs/
└── <job_name>/
    ├── input/
    │   ├── car_body.stl          ← geometry uploaded before the job starts
    │   ├── wheel_front.stl
    │   └── wheel_rear.stl
    ├── output/                   ← populated when job reaches 'done'
    │   ├── results.csv           ← timestep, drag_N, lift_N, p_residual per iteration
    │   ├── car_body.stl          ← copy of the solved geometry for the 3D viewer
    │   └── solver_fine.log       ← full fine solver output
    └── logs/                     ← only uploaded on failure
        ├── <job_name>_coarse/
        │   ├── blockMesh.log
        │   ├── surfaceFeatures.log
        │   ├── snappyHexMesh.log
        │   ├── reconstructPar_mesh.log
        │   ├── checkMesh.log
        │   ├── decomposePar.log
        │   └── solver.log
        └── <job_name>_fine/
            └── (same log files for the fine stage)
```

**`results.csv` format:**

```
timestep,drag_N,lift_N,p_residual
100,0.2134,−0.0412,8.23e-3
200,0.2089,−0.0398,2.11e-3
...
```

One row per `writeInterval`. Download this from the dashboard detail panel or directly from Firebase Storage for further analysis in Excel or Python.

### Firebase Hosting

Your dashboard is deployed at:
```
https://<your-project-id>.web.app
```

Redeployment is needed only if you edit `dashboard/index.html`. Run from the `dashboard/` folder:

```powershell
firebase deploy --only hosting
```

### Firebase Storage rules

All files under `jobs/` are publicly readable and writable — access is enforced at the UI level via the shared password, not at the storage level. If you need tighter access control, see [README.md](README.md) security notice.

---

## 5. ParaView visualisation guide

The dashboard's 3D viewer shows the car geometry but not the full flow field (pressure, velocity, vorticity). For that you need ParaView, which reads the raw OpenFOAM case files directly from the EC2 instance.

### What you need

- [ParaView](https://www.paraview.org/download/) installed on your Windows machine
- An SFTP client — [FileZilla](https://filezilla-project.org/) is recommended
- Your `cfd-key.pem` SSH key file
- The job name you want to visualise

### Step 1 — Find which instance ran the job

Open the dashboard and click the job row. Note the **instance** field (e.g. `cfd-2`). You'll need this to find the right EC2 instance.

### Step 2 — Start the instance

The instance stops itself after every job. You need to restart it manually.

1. [AWS Console](https://console.aws.amazon.com) → **EC2** → **Instances**
2. Find the instance matching the name from Step 1 (e.g. `cfd-2`)
3. Select it → **Instance state** → **Start instance**
4. Wait ~60 seconds for it to show **Running**
5. Note the **Elastic IP** — it stays the same across restarts

### Step 3 — Connect with FileZilla

1. Open FileZilla → **File** → **Site Manager** → **New site**
2. Fill in:
   - **Protocol:** SFTP
   - **Host:** `<Elastic IP of the instance>`
   - **Logon type:** Key file
   - **User:** `ubuntu`
   - **Key file:** browse to your `cfd-key.pem`
3. Click **Connect**

### Step 4 — Create the `case.foam` file

ParaView needs an empty marker file called `case.foam` in the case directory to recognise it as an OpenFOAM case.

In FileZilla, navigate to:
```
/home/ubuntu/jobs/<job_name>_fine/
```

Create an empty file called `case.foam` in that directory. In FileZilla you can do this by:
1. Right-clicking in the remote directory → **Create new file**
2. Name it `case.foam` (no extension, no content needed)

### Step 5 — Download the case folder

In FileZilla, right-click the entire `<job_name>_fine/` folder → **Download**.

This folder is large (~1–3 GB depending on mesh size and write intervals). Download it somewhere with enough disk space.

> You only need the `<job_name>_fine/` folder — the coarse case is only used as a starting point for the fine solve and is not needed for visualisation.

### Step 6 — Open in ParaView

1. Open ParaView
2. **File** → **Open** → navigate to your downloaded `<job_name>_fine/` folder
3. Select `case.foam` → **OK**
4. In the **Properties** panel on the left, click **Apply**
5. ParaView loads the mesh and all time steps

**Useful filters for aerodynamics:**

| What to see | How |
|-------------|-----|
| Pressure distribution on car | Colour by `p` — surface contour |
| Velocity field in wake | Add a **Slice** filter at Y = −0.01 m, colour by `U` magnitude |
| Vortices | Add a **Q-criterion** filter (`Gradient` → compute Q) |
| Streamlines | Add a **Stream Tracer** seeded from the inlet plane |

### Step 7 — Stop the instance when done

Once you have downloaded the case and finished in ParaView, **stop the instance** to avoid unnecessary AWS charges.

AWS Console → EC2 → select the instance → **Instance state** → **Stop instance**
