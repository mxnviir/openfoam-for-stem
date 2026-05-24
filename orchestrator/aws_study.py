r"""
aws_study.py — Windows orchestrator
Lives at orchestrator/aws_study.py inside this repo.
Called by Fusion export_stls.py with the STL folder path as argument:
  python aws_study.py "C:\Users\you\Documents\car_stls\run_01"
"""

import os
import sys
import time
import threading
import requests
import urllib.parse
import boto3
import paramiko
from pathlib import Path

# ===================== USER CONFIG =====================
# Edit this section before running your first job.
# Everything else is read from orchestrator/.env (created by setup_firebase.py).

# ── EC2 instance pool ────────────────────────────────
# Add the instance IDs you created in SETUP.md step 2i.
# Each entry needs a display name and the instance ID from the AWS console.
# Uncomment extra lines as you add more instances.
EC2_INSTANCES = [
    {"name": "cfd-2", "instance_id": "i-0REPLACE_ME"},
    # {"name": "cfd-3", "instance_id": "i-0REPLACE_ME"},
    # {"name": "cfd-4", "instance_id": "i-0REPLACE_ME"},
]
# Requirements for each instance:
#   - OpenFOAM 13 installed (done in SETUP.md step 2f)
#   - /home/ubuntu/openfoam_template/ present (SETUP.md step 2g)
#   - Elastic IP assigned (SETUP.md step 2e) so IP doesn't change on restart
#   - IAM role openfoam-ec2-role attached (SETUP.md step 2b)

EC2_USER = "ubuntu"  # change only if you use a non-ubuntu AMI

# ── Credentials & paths ──────────────────────────────
# These are read automatically from orchestrator/.env
# (created by setup_firebase.py or written manually per SETUP.md step 3a).
# You do NOT need to edit them here — edit the .env file instead.
# =======================================================

# Load credentials from .env file next to this script
def load_env():
    env_path = Path(__file__).parent / ".env"
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()

AWS_ACCESS_KEY   = ENV["AWS_ACCESS_KEY"]
AWS_SECRET_KEY   = ENV["AWS_SECRET_KEY"]
AWS_REGION       = ENV.get("AWS_REGION", "ap-south-1")
SSH_KEY_PATH     = ENV["SSH_KEY_PATH"]

FIREBASE_BUCKET  = ENV["FIREBASE_BUCKET"]
FIREBASE_API_KEY = ENV["FIREBASE_API_KEY"]
FIREBASE_PROJECT = ENV["FIREBASE_PROJECT"]


# ── Instance pool — only picks STOPPED instances ────
def get_free_instance():
    """
    Find a stopped instance and return it.
    Skips running/pending instances — they already have jobs on them.
    Blocks (polling every 30s) until a stopped instance is available.
    """
    ec2 = get_ec2_client()
    while True:
        ids = [i["instance_id"] for i in EC2_INSTANCES]
        resp = ec2.describe_instances(InstanceIds=ids)

        state_map = {}
        for r in resp["Reservations"]:
            for inst in r["Instances"]:
                state_map[inst["InstanceId"]] = inst["State"]["Name"]

        print("\n  Instance pool status:")
        for inst in EC2_INSTANCES:
            iid = inst["instance_id"]
            state = state_map.get(iid, "unknown")
            marker = "✓ FREE" if state == "stopped" else f"  {state}"
            print(f"    {inst['name']} ({iid}): {state}  {marker if state == 'stopped' else ''}")

            if state == "stopped":
                print(f"  → Claiming {inst['name']}")
                return inst

        busy = [i["name"] for i in EC2_INSTANCES
                if state_map.get(i["instance_id"]) not in ("stopped", "terminated", "unknown")]
        print(f"\n  ⏳ All instances busy: {busy}")
        print("  Waiting 30s before re-checking...")
        time.sleep(30)

def release_instance(instance_id):
    pass  # No-op — instance stops itself via self_stop() in run_job.py


# ── AWS EC2 helpers ──────────────────────────────────
def get_ec2_client():
    return boto3.client(
        "ec2", region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY
    )

def start_instance(instance_id):
    """Start instance and wait until running + SSH ready."""
    ec2 = get_ec2_client()
    print(f"  → Starting {instance_id}...")
    ec2.start_instances(InstanceIds=[instance_id])

    print("  → Waiting for instance to be running...")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])

    # Get public IP
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    ip = resp["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    print(f"  ✓ Instance running at {ip}")

    # Wait for SSH to be ready
    print("  → Waiting for SSH...")
    for attempt in range(30):
        try:
            key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, username=EC2_USER, pkey=key, timeout=10)
            client.close()
            print(f"  ✓ SSH ready (attempt {attempt+1})")
            return ip
        except Exception:
            time.sleep(10)

    raise RuntimeError(f"SSH never became ready on {instance_id} ({ip})")


# ── Firebase helpers ─────────────────────────────────
def firestore_set(job_name, data):
    fields = {}
    for k, v in data.items():
        if isinstance(v, str):    fields[k] = {"stringValue": v}
        elif isinstance(v, bool): fields[k] = {"booleanValue": v}
        else:                     fields[k] = {"doubleValue": float(v)}
    # Use updateMask so we only touch specified fields, not replace the whole doc
    mask = "&".join(f"updateMask.fieldPaths={k}" for k in data.keys())
    url = (f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}"
           f"/databases/(default)/documents/jobs/{job_name}?key={FIREBASE_API_KEY}&{mask}")
    r = requests.patch(url, json={"fields": fields})
    r.raise_for_status()

def firebase_token():
    r = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}",
        json={"returnSecureToken": True}
    )
    r.raise_for_status()
    return r.json()["idToken"]

def upload_stl(local_path, remote_path):
    encoded = urllib.parse.quote(remote_path, safe="")
    url = (f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_BUCKET}"
           f"/o/{encoded}?uploadType=media&key={FIREBASE_API_KEY}")
    with open(local_path, "rb") as f:
        data = f.read()
    r = requests.post(url, headers={
        "Content-Type": "application/octet-stream",
        "X-Goog-Upload-Protocol": "raw"
    }, data=data)
    r.raise_for_status()
    tok = r.json().get("downloadTokens", "")
    return (f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_BUCKET}"
            f"/o/{encoded}?alt=media&token={tok}")


# ── SSH run ──────────────────────────────────────────
def ssh_run(ip, command, timeout=18000):
    """SSH into instance, run command, stream output. Returns exit code."""
    key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=EC2_USER, pkey=key, timeout=30)

    transport = client.get_transport()
    transport.set_keepalive(60)

    chan = transport.open_session()
    chan.get_pty()
    chan.settimeout(timeout)
    chan.exec_command(command)

    # Stream output live
    while True:
        if chan.recv_ready():
            data = chan.recv(4096).decode("utf-8", errors="replace")
            print(data, end="", flush=True)
        if chan.exit_status_ready():
            # Drain remaining output
            while chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                print(data, end="", flush=True)
            break
        time.sleep(0.1)

    exit_code = chan.recv_exit_status()
    client.close()
    return exit_code


# ── Upload run_job.py to instance ────────────────────
def upload_run_job(ip):
    """SCP run_job.py to the instance if not already there."""
    local = str(Path(__file__).parent / "run_job.py")
    if not os.path.exists(local):
        print(f"  ⚠ run_job.py not found at {local}")
        return

    key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=EC2_USER, pkey=key, timeout=30)

    sftp = client.open_sftp()
    sftp.put(local, "/home/ubuntu/run_job.py")
    sftp.close()
    client.close()
    print("  ✓ run_job.py uploaded")


# ── Main job runner ──────────────────────────────────
def run_job(stl_folder):
    """Upload STLs, start EC2, SSH run_job.py, update Firebase."""

    job_name = Path(stl_folder).name
    stl_files = {
        "car_body.stl":    os.path.join(stl_folder, "car_body.stl"),
        "wheel_front.stl": os.path.join(stl_folder, "wheel_front.stl"),
        "wheel_rear.stl":  os.path.join(stl_folder, "wheel_rear.stl"),
    }

    # Verify STLs exist
    for fname, fpath in stl_files.items():
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Missing STL: {fpath}")

    print(f"\n{'='*50}")
    print(f"  Job: {job_name}")
    print(f"{'='*50}")

    # 1. Upload STLs to Firebase Storage
    print("\n→ Uploading STLs to Firebase Storage...")
    stl_urls = {}
    for fname, fpath in stl_files.items():
        remote = f"jobs/{job_name}/input/{fname}"
        url = upload_stl(fpath, remote)
        stl_urls[fname] = url
        print(f"  ✓ {fname}")

    # 2. Create Firestore job doc
    print("\n→ Creating Firestore job record...")
    try:
        firestore_set(job_name, {
            "job_name":   job_name,
            "status":     "queued",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "drag_N":     0.0,
            "lift_N":     0.0,
            "p_residual": 0.0,
        })
        print("  ✓ Job queued in Firestore")
    except Exception as e:
        print(f"  ⚠ Firestore write failed: {e}")

    # 3. Find a free (stopped) instance — skips any that are running/pending
    print("\n→ Looking for a free instance...")
    inst = get_free_instance()
    instance_id = inst["instance_id"]
    print(f"  ✓ Claimed {inst['name']} ({instance_id})")

    try:
        # 4. Start instance
        ip = start_instance(instance_id)

        # 5. Update Firestore: running
        try:
            firestore_set(job_name, {
                "status":     "running",
                "instance":   inst["name"],
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            print("  ✓ Firestore updated: running")
        except Exception as e:
            print(f"  ⚠ Firestore running update failed: {e}")

        # 6. Upload run_job.py
        upload_run_job(ip)

        # 7. Install dependencies on instance (idempotent)
        ssh_run(ip, "pip3 install --break-system-packages requests --quiet")

        # 8. Build env vars + run run_job.py
        env_vars = " ".join([
            f'JOB_NAME="{job_name}"',
            f'STL_CAR_BODY="{stl_urls["car_body.stl"]}"',
            f'STL_WHEEL_FRONT="{stl_urls["wheel_front.stl"]}"',
            f'STL_WHEEL_REAR="{stl_urls["wheel_rear.stl"]}"',
            f'FIREBASE_BUCKET="{FIREBASE_BUCKET}"',
            f'FIREBASE_API_KEY="{FIREBASE_API_KEY}"',
            f'FIREBASE_PROJECT="{FIREBASE_PROJECT}"',
        ])

        print(f"\n→ Running simulation on {inst['name']}...")
        # Launch job inside a screen session so it survives SSH disconnection
        # Logs go to /home/ubuntu/jobs/<job_name>/run_job.log
        screen_name = job_name.replace("/", "_")
        cmd = (
            f"export {env_vars} && "
            f"screen -dmS {screen_name} bash -c '"
            f"python3 /home/ubuntu/run_job.py "
            f"> /home/ubuntu/jobs/{job_name}/run_job.log 2>&1'"
        )
        ssh_run(ip, f"mkdir -p /home/ubuntu/jobs/{job_name}", timeout=10)

        key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
        _client = paramiko.SSHClient()
        _client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        _client.connect(ip, username=EC2_USER, pkey=key, timeout=30)
        _, stdout, _ = _client.exec_command(cmd)
        stdout.read()
        _client.close()
        print(f"  ✓ Job running in screen session '{screen_name}'")
        print(f"  → Streaming logs (Ctrl+C safe — job keeps running on EC2)...")
        print(f"  → To reattach: ssh ubuntu@{ip} -t 'screen -r {screen_name}'")

        # Wait for log file to appear then tail it live
        ssh_run(ip, f"sleep 3 && tail -f /home/ubuntu/jobs/{job_name}/run_job.log --pid=$(screen -ls | grep {screen_name} | awk '{{print $1}}' | cut -d. -f1)",
                timeout=18000)

    except Exception as e:
        print(f"\n❌ Job error: {e}")
        try:
            firestore_set(job_name, {"status": "failed"})
        except Exception:
            pass

    finally:
        release_instance(instance_id)


# ── Entry point ──────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python aws_study.py <path_to_stl_folder>")
        print("Example: python aws_study.py C:\\Users\\manvir\\Documents\\car_stls\\run_01")
        sys.exit(1)

    stl_folder = sys.argv[1]
    if not os.path.isdir(stl_folder):
        print(f"Error: folder not found: {stl_folder}")
        sys.exit(1)

    run_job(stl_folder)
