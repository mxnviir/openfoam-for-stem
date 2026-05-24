#!/usr/bin/env python3
"""
run_job.py — lives at /home/ubuntu/run_job.py on each EC2 instance
Called by aws_study.py via SSH with env vars:
  JOB_NAME, STL_CAR_BODY, STL_WHEEL_FRONT, STL_WHEEL_REAR
  FIREBASE_BUCKET, FIREBASE_API_KEY, FIREBASE_PROJECT

Workflow:
  1. Coarse run  — no boundary layers, converge to ~500 iterations
  2. Fine mesh   — with boundary layers, snappyHexMesh
  3. mapFields   — interpolate coarse solution onto fine mesh
  4. Fine run    — start from mapped fields, converge to ~1000 iterations
  5. Results     — parse forces from fine run, upload to Firebase
"""

import os, re, sys, json, struct, subprocess, requests, urllib.parse, glob

OPENFOAM_BASHRC  = "/opt/openfoam13/etc/bashrc"
TEMPLATE_DIR     = "/home/ubuntu/openfoam_template/motorBike"
JOBS_DIR         = "/home/ubuntu/jobs"
VEHICLE_SPEED    = 20.0

JOB_NAME         = os.environ["JOB_NAME"]
STL_CAR_BODY     = os.environ["STL_CAR_BODY"]
STL_WHEEL_FRONT  = os.environ["STL_WHEEL_FRONT"]
STL_WHEEL_REAR   = os.environ["STL_WHEEL_REAR"]
FIREBASE_BUCKET  = os.environ["FIREBASE_BUCKET"]
FIREBASE_API_KEY = os.environ["FIREBASE_API_KEY"]
FIREBASE_PROJECT = os.environ["FIREBASE_PROJECT"]

COARSE_DIR = os.path.join(JOBS_DIR, JOB_NAME + "_coarse")
FINE_DIR   = os.path.join(JOBS_DIR, JOB_NAME + "_fine")

N_CORES_MESH   = os.cpu_count() // 2
N_CORES_SOLVER = os.cpu_count()

COARSE_END_TIME = 500
FINE_END_TIME   = 1500

def log(msg): print(msg, flush=True)

def run(cmd, logfile=None, check=True, cwd=None):
    full_cmd = f"bash -c 'source {OPENFOAM_BASHRC} && {cmd}'"
    log(f"  $ {cmd}")
    if cwd is None:
        raise RuntimeError(f"run() called without cwd for command: {cmd}")
    work = cwd
    with subprocess.Popen(full_cmd, shell=True, cwd=work,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
        lines = []
        for line in proc.stdout:
            print(line, end='', flush=True)
            lines.append(line)
        proc.wait()
        output = "".join(lines)
        if logfile:
            log_dir = os.path.join(work, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, logfile), "w") as f:
                f.write(output)
        if check and proc.returncode != 0:
            raise RuntimeError(f"Command failed (exit {proc.returncode}): {cmd}")
        return proc.returncode, output

def firestore_update(data):
    fields = {}
    for k, v in data.items():
        if isinstance(v, str):    fields[k] = {"stringValue": v}
        elif isinstance(v, bool): fields[k] = {"booleanValue": v}
        else:                     fields[k] = {"doubleValue": float(v)}
    mask = "&".join(f"updateMask.fieldPaths={k}" for k in data.keys())
    url = (f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}"
           f"/databases/(default)/documents/jobs/{JOB_NAME}?key={FIREBASE_API_KEY}&{mask}")
    r = requests.patch(url, json={"fields": fields})
    r.raise_for_status()

def upload_storage(local_path, remote_path):
    encoded = urllib.parse.quote(remote_path, safe="")
    url = (f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_BUCKET}"
           f"/o/{encoded}?uploadType=media&key={FIREBASE_API_KEY}")
    with open(local_path, "rb") as f:
        data = f.read()
    r = requests.post(url, headers={"Content-Type": "application/octet-stream"}, data=data)
    r.raise_for_status()
    tok = r.json().get("downloadTokens", "")
    return (f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_BUCKET}"
            f"/o/{encoded}?alt=media&token={tok}")

def check_cancelled():
    try:
        url = (f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}"
               f"/databases/(default)/documents/jobs/{JOB_NAME}?key={FIREBASE_API_KEY}")
        r = requests.get(url)
        if r.ok:
            fields = r.json().get("fields", {})
            status = fields.get("status", {}).get("stringValue", "")
            return status == "cancelled"
    except Exception:
        pass
    return False

def self_stop():
    try:
        token = requests.put("http://169.254.169.254/latest/api/token",
                             headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"}, timeout=5).text
        iid    = requests.get("http://169.254.169.254/latest/meta-data/instance-id",
                              headers={"X-aws-ec2-metadata-token": token}, timeout=5).text.strip()
        region = requests.get("http://169.254.169.254/latest/meta-data/placement/region",
                              headers={"X-aws-ec2-metadata-token": token}, timeout=5).text.strip()
        log(f"  Stopping instance {iid} in {region}...")
        import boto3
        boto3.client("ec2", region_name=region).stop_instances(InstanceIds=[iid])
        log(f"  ✓ Stop signal sent")
    except Exception as e:
        log(f"  ⚠ Could not self-stop: {e}")

def parse_bounds(path):
    mn = [float('inf')]*3; mx = [float('-inf')]*3
    with open(path, 'rb') as f:
        f.read(84)
        while True:
            chunk = f.read(50)
            if len(chunk) < 50: break
            verts = struct.unpack('<9f', chunk[12:48])
            for i in range(3):
                for j in range(3):
                    mn[j] = min(mn[j], verts[i*3+j])
                    mx[j] = max(mx[j], verts[i*3+j])
    return mn, mx

def write_decompose_par(work_dir, n_cores):
    with open(os.path.join(work_dir, "system", "decomposeParDict"), "w") as f:
        f.write(f"""FoamFile {{ version 2.0; format ascii; class dictionary; location "system"; object decomposeParDict; }}
numberOfSubdomains {n_cores};
method          scotch;
""")

def write_U(work_dir, wf_axle, wr_axle, wf_omega, wr_omega):
    with open(os.path.join(work_dir, "0", "U"), "w") as f:
        f.write(f"""FoamFile {{ format ascii; class volVectorField; location "0"; object U; }}
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({VEHICLE_SPEED} 0 0);
boundaryField
{{
    inlet       {{ type fixedValue; value uniform ({VEHICLE_SPEED} 0 0); }}
    outlet      {{ type zeroGradient; }}
    lowerWall   {{ type fixedValue; value uniform ({VEHICLE_SPEED} 0 0); }}
    upperWall   {{ type noSlip; }}
    sideWall    {{ type noSlip; }}
    symmetry    {{ type symmetryPlane; }}
    car_body    {{ type noSlip; }}
    wheel_front {{ type rotatingWallVelocity; origin ({wf_axle[0]} {wf_axle[1]} {wf_axle[2]}); axis (0 1 0); omega -{wf_omega}; }}
    wheel_rear  {{ type rotatingWallVelocity; origin ({wr_axle[0]} {wr_axle[1]} {wr_axle[2]}); axis (0 1 0); omega -{wr_omega}; }}
}}
""")

def write_map_fields_dict(work_dir):
    with open(os.path.join(work_dir, "system", "mapFieldsDict"), "w") as f:
        f.write("""FoamFile
{
    format      ascii;
    class       dictionary;
    object      mapFieldsDict;
}
patchMap
(
    inlet       inlet
    outlet      outlet
    lowerWall   lowerWall
    upperWall   upperWall
    sideWall    sideWall
    symmetry    symmetry
);
cuttingPatches
(
    car_body
    wheel_front
    wheel_rear
);
""")

def patch_control_dict(work_dir, end_time, write_interval, start_from="startTime", start_time=0):
    ctrl = os.path.join(work_dir, "system", "controlDict")
    with open(ctrl) as f:
        content = f.read()
    content = re.sub(r'endTime\s+\d+', f'endTime         {end_time}', content)
    content = re.sub(r'writeInterval\s+\d+', f'writeInterval   {write_interval}', content)
    content = re.sub(r'startFrom\s+\w+', f'startFrom       {start_from}', content)
    # Only replace startTime line, not endTime line
    content = re.sub(r'(?m)^(\s*startTime\s+)\d+', f'\\g<1>{start_time}', content)
    # Remove yPlus function object to prevent size mismatch errors on restart
    content = re.sub(r'\s*yPlus\s*\{[^}]*\}', '', content, flags=re.DOTALL)
    # Ensure forces write every iteration
    content = re.sub(r'(rawForces.*?writeInterval\s+)\d+', r'\g<1>1', content, flags=re.DOTALL)
    content = re.sub(r'(forceCoeffs.*?writeInterval\s+)\d+', r'\g<1>1', content, flags=re.DOTALL)
    with open(ctrl, "w") as f:
        f.write(content)

def run_solver(work_dir, end_time, label, cancel_flag):
    """Run foamRun in background with live iteration monitoring."""
    import threading, time as _time

    log_path = os.path.join(work_dir, "logs", "solver.log")
    os.makedirs(os.path.join(work_dir, "logs"), exist_ok=True)
    cmd = f"mpirun --oversubscribe -np {N_CORES_SOLVER} foamRun -solver incompressibleFluid -parallel"
    full_cmd = f"bash -c 'source {OPENFOAM_BASHRC} && {cmd} 2>&1 | tee {log_path}'"

    solve_done = threading.Event()
    solve_result = [None]

    def _solve():
        with subprocess.Popen(full_cmd, shell=True, cwd=work_dir,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            lines = []
            for line in proc.stdout:
                print(line, end='', flush=True)
                lines.append(line)
            proc.wait()
            solve_result[0] = proc.returncode
        solve_done.set()

    t = threading.Thread(target=_solve, daemon=True)
    t.start()

    iter_times = []
    last_iter = 0
    last_wall = _time.time()
    _time.sleep(5)

    while not solve_done.is_set():
        try:
            if os.path.exists(log_path):
                with open(log_path) as lf:
                    for line in lf:
                        m = re.match(r'^Time = (\d+)', line.strip())
                        if m:
                            cur = int(m.group(1))
                            if cur > last_iter:
                                now = _time.time()
                                elapsed = now - last_wall
                                iter_times.append(elapsed)
                                if len(iter_times) > 10: iter_times.pop(0)
                                avg = sum(iter_times) / len(iter_times)
                                remaining = int((end_time - cur) * avg)
                                last_iter = cur
                                last_wall = now
                                log(f"  [{label}] iter {cur}/{end_time} — {avg:.1f}s/iter — ~{remaining//60}m remaining")
                                try:
                                    firestore_update({
                                        "process":   label,
                                        "iteration": cur,
                                        "iter_time": round(avg, 2),
                                    })
                                except Exception:
                                    pass
        except Exception:
            pass

        if check_cancelled():
            log("  ⚠ Cancellation requested — stopping solver...")
            subprocess.run("pkill -f foamRun", shell=True)
            raise RuntimeError("Job cancelled by user")

        _time.sleep(10)

    t.join()
    if solve_result[0] != 0:
        raise RuntimeError(f"foamRun failed (exit {solve_result[0]})")
    return log_path

def setup_case(work_dir, geo_dir, wf_axle, wr_axle, wf_omega, wr_omega):
    """Copy template, drop STLs, write U and decomposeParDict."""
    subprocess.run(f"rm -rf {work_dir}", shell=True)
    subprocess.run(f"cp -r {TEMPLATE_DIR} {work_dir}", shell=True, check=True)
    os.makedirs(os.path.join(work_dir, "constant", "geometry"), exist_ok=True)
    os.makedirs(os.path.join(work_dir, "logs"), exist_ok=True)
    # Remove any old time directories from template
    import glob as _glob
    for d in _glob.glob(os.path.join(work_dir, "[0-9]*")):
        if os.path.isdir(d) and os.path.basename(d) != "0":
            subprocess.run(f"rm -rf {d}", shell=True)
    # Copy STLs
    for fname in ["car_body.stl", "wheel_front.stl", "wheel_rear.stl",
                  "car_body.eMesh", "wheel_front.eMesh", "wheel_rear.eMesh"]:
        src = os.path.join(geo_dir, fname)
        if os.path.exists(src):
            subprocess.run(f"cp {src} {work_dir}/constant/geometry/", shell=True)
    write_U(work_dir, wf_axle, wr_axle, wf_omega, wr_omega)
    write_decompose_par(work_dir, N_CORES_MESH)
    subprocess.run(f"rm -rf {work_dir}/constant/polyMesh {work_dir}/processor*", shell=True)

def mesh_case(work_dir):
    """Run blockMesh → surfaceFeatures → snappy → reconstruct."""
    def r(cmd, lf): return run(cmd, logfile=lf, cwd=work_dir)
    r("blockMesh",                                                              "blockMesh.log")
    r("surfaceFeatures",                                                        "surfaceFeatures.log")
    write_decompose_par(work_dir, N_CORES_MESH)
    r("decomposePar",                                                           "decomposePar.log")
    r(f"mpirun --oversubscribe -np {N_CORES_MESH} snappyHexMesh -overwrite -parallel", "snappyHexMesh.log")
    r("reconstructPar -constant",                                               "reconstructPar_mesh.log")
    r("checkMesh",                                                              "checkMesh.log")
    subprocess.run(f"rm -rf {work_dir}/processor*", shell=True)

def main():
    import threading
    log("="*50)
    log(f"  Job: {JOB_NAME}  |  Mesh cores: {N_CORES_MESH}  |  Solver cores: {N_CORES_SOLVER}")
    log("="*50)

    cancel_flag = threading.Event()

    def _watch_cancel():
        import time as _t
        while not cancel_flag.is_set():
            if check_cancelled():
                log("  ⚠ Cancellation detected — killing processes...")
                subprocess.run("pkill -f snappyHexMesh; pkill -f foamRun; pkill -f blockMesh", shell=True)
                cancel_flag.set()
                return
            _t.sleep(15)

    watcher = threading.Thread(target=_watch_cancel, daemon=True)
    watcher.start()

    try:
        # ── 1. Download STLs into a shared geometry dir ──────────────────────
        log("\n→ Downloading STLs...")
        os.makedirs(JOBS_DIR, exist_ok=True)
        geo_dir = os.path.join(JOBS_DIR, JOB_NAME + "_geo")
        os.makedirs(geo_dir, exist_ok=True)
        for fname, url in [("car_body.stl", STL_CAR_BODY),
                           ("wheel_front.stl", STL_WHEEL_FRONT),
                           ("wheel_rear.stl", STL_WHEEL_REAR)]:
            r = requests.get(url, timeout=60); r.raise_for_status()
            with open(os.path.join(geo_dir, fname), "wb") as f: f.write(r.content)
            log(f"  ✓ {fname}")

        # ── 2. Parse geometry for wheel omega/axle ───────────────────────────
        log("\n→ Parsing geometry...")
        wf_mn, wf_mx = parse_bounds(os.path.join(geo_dir, "wheel_front.stl"))
        wr_mn, wr_mx = parse_bounds(os.path.join(geo_dir, "wheel_rear.stl"))
        def axle(mn, mx): return [(mn[i]+mx[i])/2 for i in range(3)]
        def radius(mn, mx): return (mx[2]-mn[2])/2
        wf_axle = axle(wf_mn, wf_mx); wr_axle = axle(wr_mn, wr_mx)
        wf_omega = round(VEHICLE_SPEED/radius(wf_mn, wf_mx), 2)
        wr_omega = round(VEHICLE_SPEED/radius(wr_mn, wr_mx), 2)
        log(f"  wf_omega={wf_omega}  wr_omega={wr_omega} rad/s")

        # ── 3. COARSE RUN ─────────────────────────────────────────────────────
        log("\n" + "="*50)
        log("  STAGE 1: COARSE MESH (no boundary layers)")
        log("="*50)
        firestore_update({"status": "running", "process": "coarse_mesh"})

        setup_case(COARSE_DIR, geo_dir, wf_axle, wr_axle, wf_omega, wr_omega)

        # Disable layers for coarse run
        subprocess.run(f"sed -i '/^addLayers /{{s/true/false/;s/on/false/}}' {COARSE_DIR}/system/snappyHexMeshDict", shell=True)

        # Surface features need eMesh files — run surfaceFeatures first to generate them
        mesh_case(COARSE_DIR)
        # Copy eMesh files to geo_dir for fine case
        for fname in ["car_body.eMesh", "wheel_front.eMesh", "wheel_rear.eMesh"]:
            src = os.path.join(COARSE_DIR, "constant", "geometry", fname)
            if os.path.exists(src):
                subprocess.run(f"cp {src} {geo_dir}/", shell=True)

        patch_control_dict(COARSE_DIR, end_time=COARSE_END_TIME, write_interval=100,
                           start_from="startTime", start_time=0)
        write_decompose_par(COARSE_DIR, N_CORES_SOLVER)
        run("decomposePar", logfile="decomposePar_solver.log", cwd=COARSE_DIR)
        firestore_update({"process": "coarse_solving"})
        run_solver(COARSE_DIR, COARSE_END_TIME, "coarse", cancel_flag)
        run("reconstructPar -latestTime", logfile="reconstructPar.log", cwd=COARSE_DIR)
        run("rm -rf processor*", logfile=None, cwd=COARSE_DIR)
        log("  ✓ Coarse run complete")

        # ── 4. FINE MESH ──────────────────────────────────────────────────────
        log("\n" + "="*50)
        log("  STAGE 2: FINE MESH (with boundary layers)")
        log("="*50)
        firestore_update({"process": "fine_mesh"})

        setup_case(FINE_DIR, geo_dir, wf_axle, wr_axle, wf_omega, wr_omega)

        # Ensure layers enabled
        subprocess.run(f"sed -i '/^addLayers/{{s/false/true/;s/off/true/}}' {FINE_DIR}/system/snappyHexMeshDict", shell=True)

        mesh_case(FINE_DIR)

        # ── 5. MAP FIELDS ─────────────────────────────────────────────────────
        log("\n→ Mapping fields from coarse to fine...")
        firestore_update({"process": "mapFields"})
        write_map_fields_dict(FINE_DIR)
        run(f"mapFields {COARSE_DIR} -sourceTime {COARSE_END_TIME} -noFunctionObjects",
            logfile="mapFields.log", cwd=FINE_DIR)
        log("  ✓ mapFields complete")

        # ── 6. FINE RUN ───────────────────────────────────────────────────────
        log("\n" + "="*50)
        log("  STAGE 3: FINE SOLVE")
        log("="*50)
        firestore_update({"process": "fine_solving"})

        patch_control_dict(FINE_DIR, end_time=FINE_END_TIME, write_interval=100,
                           start_from="startTime", start_time=0)
        write_decompose_par(FINE_DIR, N_CORES_SOLVER)
        run("decomposePar", logfile="decomposePar_solver.log", cwd=FINE_DIR)
        log_path = run_solver(FINE_DIR, FINE_END_TIME, "fine", cancel_flag)
        run("reconstructPar -latestTime", logfile="reconstructPar.log", cwd=FINE_DIR)
        run("rm -rf processor*", logfile=None, cwd=FINE_DIR)
        log("  ✓ Fine run complete")

        # ── 7. PARSE RESULTS ──────────────────────────────────────────────────
        log("\n→ Extracting results...")
        forces_by_time = {}
        pp_dir = os.path.join(FINE_DIR, "postProcessing", "rawForces")
        if os.path.exists(pp_dir):
            for td in sorted(os.listdir(pp_dir)):
                candidate = os.path.join(pp_dir, td, "forces.dat")
                if os.path.exists(candidate):
                    with open(candidate) as f:
                        for line in f:
                            if line.strip().startswith("#") or not line.strip(): continue
                            nums = [float(x) for x in re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", line)]
                            if len(nums) < 7: continue
                            t = int(round(nums[0]))
                            forces_by_time[t] = (nums[1]+nums[4], nums[3]+nums[6])
                    break

        p_residuals = {}
        if os.path.exists(log_path):
            current_time = None
            with open(log_path) as f:
                for line in f:
                    tm = re.match(r"^Time = (\d+)", line.strip())
                    if tm: current_time = int(tm.group(1))
                    pm = re.search(r"Solving for p,.*?Initial residual = ([0-9eE.+\-]+)", line)
                    if pm and current_time is not None:
                        p_residuals[current_time] = float(pm.group(1))

        # Average last 100 steps for final drag
        last_100_drag = [forces_by_time[t][0] for t in sorted(forces_by_time)[-100:] if t in forces_by_time]
        last_100_lift = [forces_by_time[t][1] for t in sorted(forces_by_time)[-100:] if t in forces_by_time]
        avg_drag = sum(last_100_drag)/len(last_100_drag) if last_100_drag else 0.0
        avg_lift = sum(last_100_lift)/len(last_100_lift) if last_100_lift else 0.0
        last_t   = max(forces_by_time) if forces_by_time else 0
        last_p   = p_residuals.get(last_t, 0.0)
        log(f"  ✓ Avg Drag={avg_drag:.4f}N  Avg Lift={avg_lift:.4f}N  p={last_p:.4e}")

        # Write CSV
        csv_path = os.path.join(FINE_DIR, "results.csv")
        all_times = sorted(set(list(forces_by_time.keys()) + list(p_residuals.keys())))
        with open(csv_path, "w") as f:
            f.write("timestep,drag_N,lift_N,p_residual\n")
            for t in all_times:
                drag, lift = forces_by_time.get(t, ("",""))
                p_res = p_residuals.get(t, "")
                f.write(f"{t},{'%.6f'%drag if drag!='' else ''},{'%.6f'%lift if lift!='' else ''},{'%.6e'%p_res if p_res!='' else ''}\n")

        # ── 8. UPLOAD ─────────────────────────────────────────────────────────
        log("\n→ Uploading to Firebase...")
        results_url = upload_storage(csv_path, f"jobs/{JOB_NAME}/output/results.csv")
        stl_url = upload_storage(os.path.join(geo_dir, "car_body.stl"), f"jobs/{JOB_NAME}/output/car_body.stl")
        upload_storage(log_path, f"jobs/{JOB_NAME}/output/solver_fine.log")
        log("  ✓ Uploaded")

        firestore_update({
            "status": "done", "drag_N": avg_drag, "lift_N": avg_lift,
            "p_residual": last_p, "results_url": results_url, "stl_url": stl_url,
        })

        cancel_flag.set()
        log("\n" + "="*50)
        log(f"  ✅ {JOB_NAME} COMPLETE — Drag={avg_drag:.4f}N  Lift={avg_lift:.4f}N")
        log("="*50)

    except Exception as e:
        log(f"\n  ❌ Job failed: {e}")
        try:
            firestore_update({"status": "failed"})
        except Exception:
            pass
        try:
            for work_dir in [COARSE_DIR, FINE_DIR]:
                log_dir = os.path.join(work_dir, "logs")
                if os.path.exists(log_dir):
                    for fname in os.listdir(log_dir):
                        fpath = os.path.join(log_dir, fname)
                        upload_storage(fpath, f"jobs/{JOB_NAME}/logs/{os.path.basename(work_dir)}/{fname}")
            log("  ✓ Logs uploaded")
        except Exception as ue:
            log(f"  ⚠ Could not upload logs: {ue}")
        log("\n  ⚠ Job failed — instance NOT stopped for debugging.")

    else:
        cancel_flag.set()
        log("\n→ Stopping instance...")
        self_stop()

    finally:
        cancel_flag.set()

if __name__ == "__main__":
    main()
