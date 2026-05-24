# Setup Guide

This document walks you through setting up the OpenFOAM for STEM Racing platform from scratch. Follow every section in order — by the end you will have a live dashboard and be ready to run your first simulation.

**Estimated time:** 2–3 hours (most of it is waiting for AWS things to provision)

---

## Important notices

### Costs and billing

**AWS:** AWS gives new accounts up to **$200 in free credits** — $100 credited immediately when you sign up for the AWS Educate / Activate programme, and another $100 available after completing a set of getting-started challenges. Running `c6g.2xlarge` instances at ~$0.34/hr adds up. **Once your credits are exhausted, AWS will charge your card.** It is the user's responsibility to monitor their credit balance in the AWS Billing console, stop instances when not in use, and manage their own AWS costs. We are not responsible for any AWS bills you incur.

**Firebase:** Firebase Storage requires the **Blaze (pay-as-you-go) plan** — you cannot use Storage on the free Spark plan. However, Blaze includes a generous free tier (5 GB storage, 1 GB/day downloads, 50k Firestore reads/day). In practice, **you are extremely unlikely to ever be charged by Firebase** — we ran over 200 simulations without a single Firebase charge. AWS will eat through your credits long before Firebase bills you anything. It is the user's responsibility to monitor their own Firebase usage. We are not responsible for any charges.

### Security

This platform is provided as-is for educational use. **We make no guarantees about the security of your Firebase deployment.** The dashboard uses a single shared password with no rate limiting by default — it may be vulnerable to brute-force attacks or DDoS. Your Firebase Storage and Firestore are publicly accessible to anyone who finds your project ID. It is the user's responsibility to implement appropriate rate limiting, authentication, and access controls if you expose this to the internet. We are not responsible for any security incidents, data loss, or unauthorised access.

---

## Checklist

- [ ] 0. Install tools on your Windows machine
- [ ] 1. Set up AWS infrastructure (EC2 instances)
- [ ] 2. Run automated Firebase setup script (OR manually configure Firebase — see below)
- [ ] 3. Configure Fusion 360 design
- [ ] 4. Run your first simulation

**Quick start:** After installing tools, jump to **"Quick Start — Automated Firebase Setup"** below (2 minutes). Skip the manual Firebase configuration sections if using the script.

---

## 0. Install tools on your Windows machine

Do this first — everything else depends on it.

### 0a. Python 3.9+

1. Download from [python.org](https://www.python.org/downloads/)
2. During installation, tick **"Add Python to PATH"**
3. Verify: open PowerShell and run `python --version`

### 0b. Python packages

```powershell
pip install boto3 paramiko requests python-dotenv
```

### 0c. Node.js 18+

1. Download from [nodejs.org](https://nodejs.org) (choose the LTS version)
2. Install with default settings
3. Verify: `node --version`

### 0d. Firebase CLI

```powershell
npm install -g firebase-tools
```

Verify: `firebase --version`

### 0e. Git

Download from [git-scm.com](https://git-scm.com) if you don't have it already.

---

## Quick Start — Automated Firebase Setup

If you want to skip the manual Firebase setup, use the automated script instead.

**Before running the script:**
1. Create a Firebase project in the [Firebase console](https://console.firebase.google.com) (name it something like `stemracing-cfd`)
2. Enable Firestore (Production mode) and Storage (Production mode) — regions don't matter yet
3. Create a web app to get your Firebase config (see **step 1d below** if you need help)

**Then run the setup script:**

```powershell
cd C:\path\to\openfoam-for-stem\orchestrator
python setup_firebase.py
```

The script will:
- Prompt you for Firebase credentials (API key, project ID, storage bucket, etc.)
- Prompt you for AWS credentials (access key, secret key)
- Prompt you for your SSH key path (the `.pem` file from step 2a below)
- Create an `.env` file with all credentials (inside `orchestrator/`)
- Update dashboard config files
- Create the Firestore password document
- Deploy security rules
- Deploy the dashboard to Firebase Hosting

**Time:** ~2 minutes

**After the script finishes:**
- Skip sections **1. Firebase project setup** and **4. Deploy the dashboard** (the script did those)
- Continue with section **2. AWS infrastructure setup**

---

## 1. Firebase project setup (Manual alternative)

Skip this section if you used the **automated setup script** above.

Firebase handles three things: the real-time job database (Firestore), file storage for STLs and results (Storage), and hosting the dashboard (Hosting).

Firebase handles three things: the real-time job database (Firestore), file storage for STLs and results (Storage), and hosting the dashboard (Hosting).

### 1a. Create the Firebase project

1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Click **Add project**
3. Give it a name (e.g. `stemracing-cfd`) — the Project ID underneath is what you'll use in config files, note it down
4. Google Analytics: optional, does not affect this project
5. Click **Create project**

### 1b. Enable Firestore

1. Left sidebar → **Build** → **Firestore Database**
2. Click **Create database**
3. Select **Production mode** (not test mode — the rules in this repo enforce access)
4. Choose a region close to your AWS region (e.g. `asia-south1` for Mumbai)
5. Click **Create**

### 1c. Enable Storage

1. Left sidebar → **Build** → **Storage**
2. Click **Get started**
3. Select **Production mode**
4. Use the same region as Firestore
5. Click **Done**

### 1d. Register a web app and get your config

1. Click the **gear icon** (top-left, next to "Project Overview") → **Project settings**
2. Scroll to **Your apps** → **Add app** → **Web** icon (`</>`)
3. App nickname: `dashboard`
4. Leave "Also set up Firebase Hosting" unticked
5. Click **Register app**
6. Copy the entire `firebaseConfig` object — you'll paste it into `dashboard/index.html` in step 3:

```javascript
const firebaseConfig = {
  apiKey:            "AIzaSy...",
  authDomain:        "stemracing-cfd.firebaseapp.com",
  projectId:         "stemracing-cfd",
  storageBucket:     "stemracing-cfd.firebasestorage.app",
  messagingSenderId: "123456789",
  appId:             "1:123456789:web:abc123"
};
```

7. Click **Continue to console**

### 1e. Create the password document in Firestore

The dashboard uses a single shared team password stored as a SHA-256 hash (never plaintext).

**Step 1 — Generate the hash.** In PowerShell, replace `YourTeamPassword` with your chosen password:

```powershell
python -c "import hashlib; print(hashlib.sha256(b'YourTeamPassword').hexdigest())"
```

Copy the 64-character output.

**Step 2 — Create the Firestore document:**

1. Firebase console → **Firestore Database** → click **Start collection**
2. Collection ID: `_config` → **Next**
3. Document ID: `access`
4. Add a field: `passwordHash` (type: **String**), paste the 64-character hash
5. Click **Save**

### 1f. Set up Firebase Hosting

1. Left sidebar → **Build** → **Hosting** → **Get started**
2. Click through the prompts — skip any commands it tells you to run (you'll do that via the CLI in step 4)
3. Click **Finish**

### 1g. Security rules

The rules are already in this repo (`dashboard/firestore.rules` and `dashboard/storage.rules`). They will deploy automatically when you run `firebase deploy` in step 4 — no manual editing needed.

---

## 2. AWS infrastructure setup

You need an EC2 instance pool pre-installed with OpenFOAM 13. Each instance starts stopped, gets turned on by the orchestrator for one job, then stops itself when done.

(Skip this section only if you don't have AWS instances yet — you still need to do this even with the automated Firebase setup.)

### 2a. Create an SSH key pair

1. AWS Console → **EC2** → **Key Pairs** (left sidebar, under "Network & Security")
2. Click **Create key pair**
3. Name: `cfd-key`, Type: **RSA**, Format: **.pem**
4. Click **Create key pair** — the `.pem` file downloads automatically
5. Move it somewhere permanent (e.g. `C:\Users\you\Downloads\cfd-key.pem`)

> Keep this file safe. If you lose it you cannot SSH into your instances.

### 2b. Create an IAM role for EC2 (instances stop themselves)

1. AWS Console → **IAM** → **Roles** → **Create role**
2. Trusted entity: **AWS service** → **EC2** → **Next**
3. Skip the permissions page → **Next**
4. Role name: `openfoam-ec2-role` → **Create role**
5. Open the role → **Add permissions** → **Create inline policy**
6. Click the **JSON** tab and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ec2:StopInstances",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "ec2:ResourceTag/ManagedBy": "openfoam-stemracing"
        }
      }
    }
  ]
}
```

7. **Next** → Policy name: `stop-self` → **Create policy**

### 2c. Create an IAM user for the orchestrator (your Windows machine needs AWS credentials)

1. AWS Console → **IAM** → **Users** → **Create user**
2. Username: `cfd-orchestrator` → **Next**
3. **Attach policies directly** → search for and attach **AmazonEC2FullAccess** → **Next** → **Create user**
4. Open the user → **Security credentials** tab
5. **Create access key** → **Local code** → **Next** → **Create access key**
6. **Copy both the Access Key ID and the Secret Access Key now.** You cannot retrieve the secret key again after leaving this page. Paste them into a temporary text file — you'll put them in `.env` in step 3.

### 2d. Launch the base instance (cfd-1)

1. EC2 → **Instances** → **Launch instances**
2. **Name**: `cfd-1`
3. **AMI**: search `Ubuntu` → **Ubuntu Server 22.04 LTS (arm64)**
4. **Instance type**: `c6g.2xlarge` (8 vCPU, 16 GB RAM, ARM-based, ~$0.34/hr)
5. **Key pair**: `cfd-key`
6. **Network settings** → **Edit** → **Add security group rule**: SSH, Source: **My IP**
7. **Advanced details**:
   - IAM instance profile: `openfoam-ec2-role`
   - Tags → **Add tag**: Key = `ManagedBy`, Value = `openfoam-stemracing`
8. **Launch instance**

Wait ~1 minute for "running" status. Note the **Public IPv4 address**.

### 2e. Assign an Elastic IP to cfd-1

Without an Elastic IP the instance gets a new address every time it starts.

1. EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**
2. Select the new IP → **Actions** → **Associate Elastic IP address**
3. Instance: `cfd-1` → **Associate**

Note this IP — it's how you'll SSH in.

### 2f. Install OpenFOAM 13 on cfd-1

Open Git Bash or PowerShell and SSH in:

```bash
ssh -i C:\Users\you\Downloads\cfd-key.pem ubuntu@<cfd-1-elastic-ip>
```

Type `yes` when asked about the host fingerprint. Once connected:

```bash
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get update
sudo apt-get install -y openfoam13

sudo apt-get install -y python3-pip
pip3 install firebase-admin boto3
```

This takes 5–10 minutes. When it finishes, type `exit`.

### 2g. Download and copy the OpenFOAM template to cfd-1

The OpenFOAM case template is **not included in this repository** — it is hosted on Google Drive to avoid bloating the repo with large binary files and case-specific geometry.

**Download the template:**

1. Open the shared folder: **[OpenFOAM Template — Google Drive](https://drive.google.com/drive/folders/10Rwj5sGinvybAW3fao9YXHiLTU_0X18E?usp=sharing)**
2. Click the folder name → **Download** (Google Drive will zip it for you)
3. Extract the zip — you should have a folder called `openfoam_template/` containing a `motorBike/` subfolder

**Upload it to cfd-1** (from Git Bash — not PowerShell, `scp` works better there):

```bash
scp -i /c/Users/you/Downloads/cfd-key.pem -r /c/Users/you/Downloads/openfoam_template ubuntu@<cfd-1-elastic-ip>:/home/ubuntu/
```

Verify it arrived:

```bash
ssh -i /c/Users/you/Downloads/cfd-key.pem ubuntu@<cfd-1-elastic-ip> "ls /home/ubuntu/openfoam_template"
```

You should see `motorBike` listed.

> **Note:** This template was built and tuned for a specific STEM car geometry. Read **Section 5d.5** before running your first simulation — you will likely need to adjust the domain size, refinement box positions, and reference values for your car. The template is intentionally kept out of this git repository — do not commit it.

### 2h. Create an AMI from cfd-1

1. EC2 console → select `cfd-1` → **Actions** → **Image and templates** → **Create image**
2. Image name: `openfoam-cfd-base`
3. **Create image**

Wait until AMI status shows **available** (EC2 → AMIs). Takes 5–15 minutes.

### 2i. Launch the instance pool

Launch 3–5 instances from the AMI (one per team member who might run simultaneous simulations).

For each pool instance (`cfd-2`, `cfd-3`, etc.):

1. EC2 → **Launch instances**
2. **Name**: `cfd-2` (increment for each)
3. **AMI**: **My AMIs** → `openfoam-cfd-base`
4. **Instance type**: `c6g.2xlarge`
5. **Key pair**: `cfd-key`
6. **Network settings**: same security group as `cfd-1`
7. **Advanced details**: IAM profile = `openfoam-ec2-role`, Tag = `ManagedBy = openfoam-stemracing`
8. **Launch**

After each launch, assign it an Elastic IP (repeat step 2e). **Write down the instance ID** (e.g. `i-0abc123def456`) for each one — you need them in step 3.

**Stop all pool instances** once they're running. The orchestrator starts them on demand.

---

## 3. Configure local files

**If you used the automated Firebase setup script:** The script already created `.env`, updated `.firebaserc`, and updated `dashboard/index.html`. Skip to **step 3b** (only `export_stls.py` and `aws_study.py` need manual edits).

**If you did manual Firebase setup:** Do all steps 3a–3f before moving on.

### 3a. Create the `.env` file (skip if using automated setup)

In the `orchestrator/` folder (same folder as `aws_study.py`), create a file named `.env`:

```ini
# AWS credentials — from step 2c
AWS_ACCESS_KEY=AKIA...
AWS_SECRET_KEY=...
AWS_REGION=ap-south-1

# Full path to your .pem key file (use forward slashes)
SSH_KEY_PATH=C:/Users/you/Downloads/cfd-key.pem

# Firebase credentials — from step 1d (firebaseConfig values)
FIREBASE_API_KEY=AIzaSy...
FIREBASE_BUCKET=your-project-id.firebasestorage.app
FIREBASE_PROJECT=your-project-id
```

**Where to find each value:**

- `AWS_ACCESS_KEY` and `AWS_SECRET_KEY` — saved in step 2c
- `SSH_KEY_PATH` — path to your `.pem` file (from step 2a)
- `FIREBASE_API_KEY` — the `apiKey` value from the `firebaseConfig` in step 1d
- `FIREBASE_BUCKET` — the `storageBucket` value from the `firebaseConfig` in step 1d
- `FIREBASE_PROJECT` — the `projectId` value from the `firebaseConfig` in step 1d (also your Project ID from step 1a)

> This file is in `.gitignore` and will never be committed. **Do not share it or commit it to version control.**

### 3b. Edit `orchestrator/export_stls.py`

Open `orchestrator/export_stls.py` and update these two lines near the top:

```python
# Line 4 — where exported STL folders are created on your Windows machine
BASE_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "car_stls")

# Line 7 — full path to aws_study.py on your machine
AWS_STUDY_PATH = os.path.join(os.path.expanduser("~"), "Documents", "f1-cfd", "aws_study.py")
```

Change `AWS_STUDY_PATH` to wherever you cloned this repo. For example:

```python
AWS_STUDY_PATH = r"C:\Users\you\Downloads\openfoam-for-stem\orchestrator\aws_study.py"
```

You can leave `BASE_FOLDER` as-is (it uses your Windows `Documents` folder) or point it somewhere else.

### 3c. Edit `orchestrator/aws_study.py`

Open `orchestrator/aws_study.py` and update the EC2 instance pool (lines 45–50):

**EC2 instance pool** (use the instance IDs you noted in step 2i):

```python
EC2_INSTANCES = [
    {"name": "cfd-2", "instance_id": "i-0abc123def456"},
    {"name": "cfd-3", "instance_id": "i-0xyz789abc123"},
    # add more as needed
]
```

Replace `i-0abc123def456` with your actual instance IDs. Remove or comment out any entries for instances you haven't created yet.

**Firebase settings** are now read from the `.env` file (step 3a), so no editing of Firebase lines is needed here.

### 3d. `orchestrator/run_job.py` — no changes needed

The Firebase project ID is now automatically read from the `FIREBASE_PROJECT` environment variable (set in `.env` from step 3a), so no manual editing is required.

### 3e. Update the dashboard Firebase config (skip if using automated setup)

Open `dashboard/index.html`. Search for `const firebaseConfig` and replace the placeholder values with the actual ones from your `firebaseConfig` copied in step 1d:

```javascript
const firebaseConfig = {
  apiKey:            "AIzaSy...",                                    // from step 1d
  authDomain:        "your-project-id.firebaseapp.com",             // from step 1d
  projectId:         "your-project-id",                             // your Project ID
  storageBucket:     "your-project-id.firebasestorage.app",         // from step 1d
  messagingSenderId: "123456789",                                    // from step 1d
  appId:             "1:123456789:web:abc123"                        // from step 1d
};
```

Replace `YOUR_FIREBASE_*` placeholders with the exact values from your Firebase `firebaseConfig` object (from step 1d).

### 3f. Update the Firebase project reference (skip if using automated setup)

Open `dashboard/.firebaserc` and replace `f1-cfd` with your Project ID:

```json
{
  "projects": {
    "default": "your-project-id"
  }
}
```

---

## 4. Deploy the dashboard (skip if using automated setup)

**If you used the automated Firebase setup script:** This was done automatically. Skip this section.

**If you did manual Firebase setup:** Continue with the steps below.

### 4a. Log in to Firebase

```powershell
firebase login
```

This opens your browser. Log in with the same Google account that owns the Firebase project.

### 4b. Deploy

```powershell
cd C:\path\to\openfoam-for-stem\dashboard
firebase deploy
```

This deploys the static dashboard, Firestore rules, and Storage rules in one go.

Successful output:

```
✔  Deploy complete!
Hosting URL: https://your-project-id.web.app
```

Open the Hosting URL. You should see the login page. Enter the password you set in step 1e — you should see an empty jobs table.

> If you see "Could not reach database", double-check the `firebaseConfig` in `dashboard/index.html` and redeploy.

---

## 5. Fusion 360 design guidelines

This section explains how to set up your Fusion 360 model so that `export_stls.py` produces files OpenFOAM can use. OpenFOAM is extremely picky about geometry — small issues that look fine visually will cause the mesher to crash or produce garbage results.

### 5a. Car orientation and wheel placement

The CFD domain is a virtual wind tunnel with a moving ground plane. The domain is set up like this:

```
Inlet (wind enters)          Car sits here           Outlet (wind exits)
X = -0.339 m  ──── wind flows +X ────►  X = 0 to 0.215 m  ────►  X = 0.871 m

               Symmetry plane (right side of car)
               Y = 0 ─────────────────────────────────
               Car body extends to Y = -0.170 m (left side)

               Ground plane: Z = 0
               Top of domain: Z = 0.213 m
```

Wind enters from the **−X side** at 20 m/s and flows in the **+X direction**. The car is stationary in the domain. Wind hits the **nose first**, so the **nose must face the −X side (toward the inlet)**.

| Axis | Direction |
|------|-----------|
| **X** | Flow direction — **nose at low X** (≈ X = 0), **rear at high X** (≈ X = 0.2 m). Wind enters from −X and hits the nose first. |
| **Y** | Lateral — the car's **right-side centreline sits on Y = 0** (symmetry plane). The car extends into **negative Y** (left side of car to Y ≈ −0.055 m). Only the left half of the car is simulated. |
| **Z** | Up — **wheel contact patches at Z = 0** (ground plane). Car body above Z = 0. Nothing below Z = 0. |

**Car position in the domain (approximate, based on the template):**

| Part | Expected X | Expected Y | Expected Z |
|------|-----------|-----------|-----------|
| Nose tip | ≈ 0 m | 0 (centreline) | ≈ 0.02 m |
| Rear/tail | ≈ 0.2–0.215 m | 0 (centreline) | ≈ 0.02 m |
| Wheel centres | — | ≈ −0.037 m | ≈ 0.018 m |
| Wheel ground contact | — | — | = 0 m |

**Wheel requirements:**
- Wheel axles must be aligned with the **Y axis** — the script calculates omega (`ω = v/r`) and rotation origin from the bounding box of each wheel STL
- `run_job.py` automatically reads the bounding box to find the axle centre and radius — this only works if the wheel is correctly oriented (axle along Y, not X or Z)

**Pre-export checklist:**
- ✅ **Nose faces −X** (toward the inlet). From the front of the car, you are looking in the +X direction.
- ✅ **Wheel bottoms touch Z = 0** — no wheels floating above the ground or sinking through it
- ✅ **Car centreline on Y = 0** — the car is symmetric and its right side sits on the symmetry plane
- ✅ **Nothing below Z = 0** — no bodywork underground
- ✅ **Wheel axles are parallel to the Y axis** — wheels spin around Y, not X or Z
- ✅ Car body is entirely within X: [−0.339, 0.871] and Y: [−0.170, 0] — nothing outside the domain

**Quick orientation check:** After exporting, open `car_body.stl` in [ViewSTL.com](https://www.viewstl.com). From the default front view, the car's nose should be on the left (−X side) with the car body extending to the right. Wheels should sit flat at the bottom (Z = 0).

### 5a.5. Check for unconnected bodies

Before exporting, you **must** ensure there are no floating or unconnected geometry pieces. Every body in your design should be part of the car — no loose parts, construction geometry, or reference objects.

**How to check:**
1. In Fusion 360, open the **Design** tab and expand **Bodies** in the model tree
2. Verify every visible body is part of the car (chassis, wings, wheels, sidepods, halo, helmet, etc.)
3. Hide or delete any construction bodies, references, or placeholder objects
4. Make sure the halo and helmet are present (see **5c** below)

**Common issues:**
- Sketch planes or construction sketches visible → hide them
- Old test geometries or previous wheel designs still visible → delete them or hide them
- Bodies from imported STEP files not positioned → they'll export with bad geometry if disconnected from the assembly

---

### 5b. Body naming conventions

The export script (`export_stls.py`) categorises every visible body in your design by name and exports them into three STL files. The naming rules are:

| Body name contains | Exported to |
|-------------------|-------------|
| Does **not** contain "wheel" | `car_body.stl` (all combined into one) |
| "wheel" + "front" | `wheel_front.stl` (all combined into one) |
| "wheel" + "rear" or "back" | `wheel_rear.stl` (all combined into one) |
| "wheel" but no front/rear/back | Skipped with a warning |

**Rules:**
- Names are case-insensitive
- All visible bodies that do not contain "wheel" go into `car_body.stl` — this includes the chassis, bodywork, halo, helmet, sidepods, wings, floor, etc.
- Bodies that are hidden (light bulb off in the browser) are ignored
- Multiple front-wheel bodies (e.g. `wheel_front_left`, `wheel_front_right`) are combined into a single `wheel_front.stl` — OpenFOAM treats both front wheels as one rotating patch

**Example naming that works:**
```
chassis
front_wing_assembly
rear_wing_main
sidepod_left
halo
helmet_body
wheel_front_left
wheel_front_right
wheel_rear_left
wheel_rear_right
```

**Common mistakes:**
- Naming a wheel `tire_front` — has no "wheel" in the name so it gets merged into `car_body.stl` incorrectly
- Naming a sidepod `wheel_pod` — gets misclassified as a wheel body and skipped
- Leaving placeholder or construction bodies visible — they'll end up in `car_body.stl`

### 5c. Halo and helmet geometry

The STEM kit's default halo and helmet STEP files have geometry issues (gaps, non-manifold edges, overlapping faces) that OpenFOAM's surface mesher (`snappyHexMesh`) will reject. The mesher needs fully watertight, clean geometry — any open edge or self-intersection causes the mesh generation to fail or produce cells inside the geometry.

This repo includes pre-fixed halo and helmet geometry files in `assets/fusion_geometry/`:

```
assets/
└── fusion_geometry/
    ├── halo.step   or   halo.ipt        ← fixed for OpenFOAM compatibility
    └── helmet.step  or  helmet.ipt      ← fixed for OpenFOAM compatibility
```

Files may be in either `.step` (universal) or `.ipt` (Inventor/Fusion native) format — use whichever your version of Fusion 360 imports cleanly.

> **Credit:** The halo geometry was provided by **Team Avium** and the helmet geometry by **Team Pegasus**. These are not our work — thank you to both teams for making them available.

**To use them in your Fusion 360 design:**

1. Open your car design in Fusion 360
2. **Insert** → **Insert STEP** → select `assets/fusion_geometry/halo.step`
3. Position and orient the halo to fit your car (match the mounting points to your roll hoop)
4. Repeat for `assets/fusion_geometry/helmet.step` — position the helmet inside the halo at the driver's head
5. Make sure both components are in the root component (not buried in a sub-component) so the script can find them
6. The halo and helmet bodies should **not** have "wheel" in their names — they'll automatically export as part of `car_body.stl`

**Before exporting, verify:**
- ✅ Both the halo and helmet are visible in the design
- ✅ They are positioned at the correct height and lateral position (matching your car's geometry)
- ✅ They don't intersect with other bodies (no overlapping geometry)
- ✅ In the Bodies panel, you should see both halo and helmet as separate bodies (if they were imported from STEP files)
- ✅ Run **Inspect** → **Body Analysis** on both to confirm they are watertight (green/valid, not red/invalid)

**Geometry requirements for any body you add:**
- Watertight (no open edges) — check with Fusion's **Inspect** → **Body Analysis**
- No self-intersecting faces
- No zero-area faces or degenerate triangles
- The body must be a solid BRep body, not a mesh or surface body

If you design your own halo or helmet, export it as STL first and check it with [MeshLab](https://www.meshlab.net/) or [netfabb](https://www.autodesk.com/products/netfabb) before using it in a simulation.

### 5d.5. Verify the OpenFOAM template matches your car

The template was built and tuned for one specific STEM car. If your car is a different size, shape, or scale you must verify — and possibly update — these four things before your first simulation. **Do not skip this step or your results will be wrong.**

#### What to check in `system/blockMeshDict`

The domain currently spans:
```
X: -0.339 m  →  0.871 m   (total length: ~1.21 m)
Y: -0.170 m  →  0 m       (half-car width, right side on symmetry at Y=0)
Z: -0.0003 m →  0.213 m   (height)
```

**Your car must fit comfortably inside this box.** Rules of thumb:
- At least **1× car length** of clear space upstream of the nose (between X = −0.339 and X = 0)
- At least **3× car length** of clear space downstream of the tail (between X ≈ 0.2 and X = 0.871)
- At least **2× car half-width** of clear space between the car side and Y = −0.170
- At least **2× car height** of clear space between the car roof and Z = 0.213

If your car does not fit within these clearances, you need to edit the vertex coordinates in `blockMeshDict` to make the domain larger. Also update the `blocks` resolution line `(151 21 27)` proportionally — more cells means longer meshing time.

#### What to check in `system/snappyHexMeshDict`

The refinement boxes are positioned around the original car:
```python
refinementBoxWake  min (-0.020, -0.055, 0.000)  max (0.500, 0.005, 0.065)
refinementBoxMid   min (-0.020, -0.055, 0.000)  max (0.230, 0.005, 0.060)
refinementBoxHigh  min (-0.005, -0.045, 0.000)  max (0.215, 0.003, 0.055)
```

**Reposition these boxes to cover your car:**
- `refinementBoxHigh` should tightly surround your car body (nose to tail, wheel to wheel, floor to roof)
- `refinementBoxMid` should be slightly larger — roughly 1.5× the car in all directions
- `refinementBoxWake` should extend **behind** the car by 2–3× the car length (downstream, +X direction)

The `locationInMesh` point `(0.500 -0.085 0.060)` must stay **outside** your car body and **inside** the domain. If your car extends past X = 0.5, move this point further downstream.

#### What to update in `system/controlDict`

These three values are specific to the original car and **must** be updated for your car:

```c++
// Car frontal area (half model — only one side since symmetry plane halves the car)
Aref  0.001445;    // ← Replace with: (car_width/2) × car_height, in m²

// Characteristic length (typically the wheelbase or car length)
lRef  0.220;       // ← Replace with your car's wheelbase in metres

// Centre of rotation for force calculation (roughly the centre of your car)
CofR  (0.101 0 0.021);   // ← Replace with (car_midlength, 0, car_midheight)
```

To measure your car's dimensions in Fusion 360: **Inspect** → **Measure** → select two points on the body.

`Aref` is the **half frontal area** (only the half-car is simulated). To get the full frontal area, measure the maximum width × height of your car, then divide by 2. Wrong `Aref` means drag and lift *coefficients* (Cd, Cl) will be wrong — absolute forces (N) are unaffected.

#### Wheel rotation — automatic, but verify

The script `run_job.py` calculates wheel omega (`ω = V / r`) and the rotation axis origin automatically from the wheel STL bounding box:
- **Axle centre**: midpoint of the bounding box in X, Y, Z
- **Radius**: half the Z-extent of the bounding box (i.e., `(z_max − z_min) / 2`)

This only works correctly if:
1. The wheel is truly round (a circular cross-section in the Y-Z plane)
2. The axle is parallel to the Y axis (not tilted)
3. The wheel is correctly positioned with its contact patch at Z = 0

The script prints the calculated values when it runs — check the terminal output:
```
wf_omega=28.57  wr_omega=28.57 rad/s
```
At 20 m/s, a wheel with 0.7 m diameter (radius 0.35 m) should give ω ≈ 57 rad/s. A wheel with 0.035 m radius gives ω ≈ 571 rad/s. Verify the number makes sense for your car's wheel size.

---

### 5d. Wings and small features

OpenFOAM's snappyHexMesh struggles with very thin features (< ~2 mm in real-world scale). Very thin rear wing endplates or bargeboards may be skipped or cause mesh failures. Practical guidelines:

- Minimum wall thickness: ~5 mm real-world (0.005 m in the STL)
- Sharp trailing edges: slightly blunt them (1–2 mm radius) — a perfectly sharp edge is geometrically zero-thickness and the mesher can't resolve it
- Complex overlapping assemblies (e.g. multi-element wings with very small gaps): simplify to single-element for meshing purposes if you get mesh failures

---

## 6. Viewing logs and debugging OpenFOAM

When a job is running or has failed, you can inspect the full solver output by SSHing into the EC2 instance.

### 6a. SSH into the instance

Find the instance's Elastic IP (in the AWS console or from the orchestrator output). Then:

```bash
ssh -i C:/Users/you/Downloads/cfd-key.pem ubuntu@<instance-elastic-ip>
```

### 6b. Watch the live job log

The orchestrator streams logs to your terminal while it's connected. If you closed the terminal or want to reconnect:

```bash
# Tail the main job log (replaces the terminal stream)
tail -f /home/ubuntu/jobs/<job_name>/run_job.log

# Or reattach to the screen session (gives you an interactive view)
screen -r <job_name>
# To detach without killing it: Ctrl+A, then D
```

### 6c. Per-stage OpenFOAM logs

Each solver stage writes its own log file. These are the most useful for diagnosing OpenFOAM errors:

```
/home/ubuntu/jobs/<job_name>_coarse/logs/
├── blockMesh.log           ← background mesh generation
├── surfaceFeatures.log     ← edge detection on STLs
├── snappyHexMesh.log       ← mesh generation (most failures happen here)
├── reconstructPar_mesh.log ← parallel mesh reconstruction
├── checkMesh.log           ← mesh quality report
├── decomposePar.log        ← domain decomposition for parallel solving
└── solver.log              ← foamRun output (residuals, iteration times)

/home/ubuntu/jobs/<job_name>_fine/logs/
└── (same files for the fine-mesh stage)
```

To read a log:

```bash
cat /home/ubuntu/jobs/<job_name>_coarse/logs/snappyHexMesh.log | less
# Press Q to exit less
```

To search for errors:

```bash
grep -i "error\|fatal\|illegal\|failed" /home/ubuntu/jobs/<job_name>_coarse/logs/snappyHexMesh.log
```

### 6d. Logs uploaded to Firebase on failure

When a job fails, `run_job.py` automatically uploads all log files to Firebase Storage under:

```
jobs/<job_name>/logs/
├── <job_name>_coarse/
│   └── (all log files)
└── <job_name>_fine/
    └── (all log files)
```

You can download them from the Firebase console → **Storage** → navigate to the path above. This means you can inspect failure logs without SSH access.

### 6e. Common OpenFOAM errors

| Error in log | Likely cause | Fix |
|---|---|---|
| `Fatal error in snappyHexMesh: open edges detected` | Non-watertight STL geometry | Check body in Fusion 360 → Inspect → Body Analysis; use the provided halo/helmet STEP files |
| `FOAM FATAL ERROR: cannot find file "constant/geometry/car_body.stl"` | STL files didn't download | Check Firebase Storage URLs and internet connectivity on the instance |
| `Illegal triangles: ...` | Degenerate faces in STL | Run STL through MeshLab → Filters → Cleaning → Remove Duplicate Faces |
| `foamRun: command not found` | OpenFOAM sourcing failed | SSH in and run: `source /opt/openfoam13/etc/bashrc && foamRun --version` |
| `mpirun: command not found` | MPI not installed | Run: `sudo apt-get install -y openmpi-bin libopenmpi-dev` |
| Solver residuals not converging (p residual stays > 1e-2) | Bad initial conditions or geometry | Run more coarse iterations; check STL orientation matches the wind direction |

---

## 7. Run a test simulation

### 7a. Export STLs from Fusion 360

1. Open your car design in Fusion 360
2. Press `Shift+S` → **Scripts and Add-Ins** → **Add** → navigate to `orchestrator/export_stls.py`
3. Click **Run**
4. Enter a name when prompted (e.g. `run_01`)
5. When asked about debug mode, enter `no` for a real simulation
6. The script exports STLs and opens a terminal window to launch the simulation automatically

If the terminal doesn't open (e.g. `aws_study.py` path is wrong), you can launch manually:

```powershell
python orchestrator/aws_study.py "C:\Users\you\Documents\car_stls\run_01"
```

### 7b. Monitor in the dashboard

Open your Hosting URL (`https://your-project-id.web.app`). The job appears within a minute. Click the row to see the 3D viewer and live graphs.

The full simulation takes about 3 hours. You can close the terminal — the EC2 instance runs independently and stops itself when done.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `firebase: command not found` | Run `npm install -g firebase-tools` and restart your terminal |
| Firebase login fails | Make sure you're logging in with the same Google account that owns the Firebase project |
| "Could not reach database" on dashboard login | Verify `_config/access` exists in Firestore with a `passwordHash` field. Re-check the `firebaseConfig` in `dashboard/index.html` |
| Password doesn't work | Re-run: `python -c "import hashlib; print(hashlib.sha256(b'YourPassword').hexdigest())"` and paste the exact 64-character output into Firestore |
| `firebase deploy` fails on rules | Make sure you're running it from the `dashboard/` folder, not the project root |
| `firebase deploy` says "project not found" | Check `dashboard/.firebaserc` contains your correct Project ID |
| `scp` fails to copy the template | Use Git Bash (not PowerShell) with forward slashes in the path |
| SSH connection refused | Wait 60 seconds after starting the instance; check the security group allows port 22 from your IP |
| Python script fails with "module not found" | Run `pip install boto3 paramiko requests python-dotenv` |
| EC2 instance won't start | Verify `openfoam-ec2-role` is attached and the tag `ManagedBy = openfoam-stemracing` is set |
| Job stuck on `queued` | SSH in and check: `tail -f /home/ubuntu/jobs/<job_name>/run_job.log` |
| snappyHexMesh fails with open edges | Your STL geometry has holes — use the provided halo/helmet STEP files; check all other bodies with Fusion's body analysis tool |
| Firestore permission denied on EC2 | Verify you updated both `f1-cfd` occurrences in `run_job.py` to your Project ID |

---

> See [README.md](README.md) for usage instructions and how to scale the instance pool.
> See [DOCS.md](DOCS.md) for the full reference guide — dashboard metrics, Firebase structure, OpenFOAM settings, and the ParaView visualisation guide.
