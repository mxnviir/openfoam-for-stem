#!/usr/bin/env python3
"""
setup_firebase.py — Automated Firebase setup for the CFD dashboard
Configures Firestore, Cloud Storage, and Firebase Hosting with proper security rules.
"""

import os
import sys
import json
import hashlib
import subprocess
import requests
from pathlib import Path
from getpass import getpass


def print_header(msg):
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}\n")


def print_success(msg):
    print(f"✓ {msg}")


def print_error(msg):
    print(f"✗ {msg}", file=sys.stderr)


def print_warning(msg):
    print(f"⚠ {msg}")


def get_input_with_validation(prompt, validator=None, is_password=False):
    """Prompt user for input with optional validation."""
    while True:
        if is_password:
            value = getpass(prompt)
        else:
            value = input(prompt).strip()

        if not value:
            print_error("  This field cannot be empty")
            continue

        if validator and not validator(value):
            print_error("  Invalid input")
            continue

        return value


def validate_project_id(pid):
    """Firebase project IDs are lowercase, alphanumeric with hyphens."""
    return pid.replace("-", "").replace("_", "").isalnum() and len(pid) > 0


def validate_api_key(key):
    """Firebase API keys are typically long alphanumeric strings."""
    return len(key) > 20 and key.replace("-", "").replace("_", "").isalnum()


def validate_bucket(bucket):
    """Cloud Storage bucket names follow specific rules."""
    return bucket.endswith(".appspot.com") or len(bucket) > 0


def create_env_file(firebase_project, firebase_api_key, firebase_bucket,
                   aws_access_key, aws_secret_key, ssh_key_path, aws_region):
    """Create or update .env file in orchestrator directory."""
    env_path = Path(__file__).parent / ".env"

    env_content = f"""# Firebase Configuration
FIREBASE_PROJECT={firebase_project}
FIREBASE_API_KEY={firebase_api_key}
FIREBASE_BUCKET={firebase_bucket}

# AWS Configuration
AWS_REGION={aws_region}
AWS_ACCESS_KEY={aws_access_key}
AWS_SECRET_KEY={aws_secret_key}
SSH_KEY_PATH={ssh_key_path}
"""

    with open(env_path, "w") as f:
        f.write(env_content)

    # Protect the .env file on Windows
    try:
        import stat
        os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
        print_success(f".env file created at {env_path}")
    except Exception as e:
        print_warning(f"Could not set file permissions: {e}")


def update_firebaserc(firebase_project):
    """Update dashboard/.firebaserc with project ID."""
    dashboard_path = Path(__file__).parent.parent / "dashboard" / ".firebaserc"

    content = {"projects": {"default": firebase_project}}

    with open(dashboard_path, "w") as f:
        json.dump(content, f, indent=2)

    print_success(f".firebaserc updated with project '{firebase_project}'")


def update_dashboard_config(firebase_project, firebase_api_key,
                          firebase_messaging_sender_id, firebase_app_id):
    """Update dashboard/index.html with Firebase configuration."""
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"

    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace Firebase config in index.html
    config_block = f"""const firebaseConfig = {{
      apiKey: "{firebase_api_key}",
      authDomain: "{firebase_project}.firebaseapp.com",
      projectId: "{firebase_project}",
      storageBucket: "{firebase_project}.firebasestorage.app",
      messagingSenderId: "{firebase_messaging_sender_id}",
      appId: "{firebase_app_id}"
    }};"""

    # Find and replace the config section
    import re
    config_pattern = r"const firebaseConfig = \{[^}]*\};"

    if re.search(config_pattern, content):
        content = re.sub(config_pattern, config_block, content, flags=re.DOTALL)
    else:
        print_warning("Could not find firebaseConfig in index.html")
        return False

    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(content)

    print_success("Firebase config updated in index.html")
    return True


def create_firestore_config(firebase_project, firebase_api_key, password_hash):
    """Create _config/access document in Firestore with password hash."""
    # Firestore REST API endpoint for document creation
    url = (f"https://firestore.googleapis.com/v1/projects/{firebase_project}"
           f"/databases/(default)/documents/_config"
           f"?documentId=access&key={firebase_api_key}")

    payload = {
        "fields": {
            "passwordHash": {"stringValue": password_hash}
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code in [200, 201]:
            print_success("_config/access document created in Firestore")
            return True
        elif response.status_code == 409:
            # Document already exists — try to update it
            print_warning("Document already exists, updating...")
            doc_url = (f"https://firestore.googleapis.com/v1/projects/{firebase_project}"
                      f"/databases/(default)/documents/_config/access"
                      f"?key={firebase_api_key}")
            update_response = requests.patch(doc_url, json=payload, timeout=10)
            if update_response.status_code == 200:
                print_success("_config/access document updated in Firestore")
                return True
            else:
                print_error(f"Failed to update: {update_response.text}")
                return False
        else:
            print_error(f"Failed to create Firestore document: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print_error(f"Failed to create Firestore document: {e}")
        print_warning("You can create it manually: Firebase console → Firestore → _config collection → access document")
        return False


def deploy_firebase_rules(firebase_project):
    """Deploy Firestore and Storage rules using Firebase CLI."""
    dashboard_path = Path(__file__).parent.parent / "dashboard"

    try:
        # Check if firebase CLI is installed
        subprocess.run(["firebase", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("Firebase CLI not installed. Install with: npm install -g firebase-tools")
        return False

    print("\n📤 Deploying Firebase rules...")

    try:
        # Deploy rules
        result = subprocess.run(
            ["firebase", "deploy", "--only", "firestore,storage", "--project", firebase_project],
            cwd=dashboard_path,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print_success("Firebase rules deployed successfully")
            return True
        else:
            print_error(f"Failed to deploy rules: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print_error("Firebase deployment timed out")
        return False
    except Exception as e:
        print_error(f"Error deploying rules: {e}")
        return False


def deploy_firebase_hosting(firebase_project):
    """Deploy Firebase Hosting."""
    dashboard_path = Path(__file__).parent.parent / "dashboard"

    print("\n📤 Deploying Firebase Hosting...")

    try:
        result = subprocess.run(
            ["firebase", "deploy", "--only", "hosting", "--project", firebase_project],
            cwd=dashboard_path,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            print_success("Firebase Hosting deployed successfully")
            # Extract the hosting URL from output
            if "Hosting URL:" in result.stdout:
                url = result.stdout.split("Hosting URL:")[1].strip().split()[0]
                print_success(f"Dashboard available at: {url}")
            return True
        else:
            print_error(f"Failed to deploy hosting: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print_error("Firebase hosting deployment timed out")
        return False
    except Exception as e:
        print_error(f"Error deploying hosting: {e}")
        return False


def main():
    print_header("Firebase Configuration Setup")

    print("This script will configure Firebase Firestore, Cloud Storage, and Hosting.")
    print("You'll need:")
    print("  • Firebase project ID (from Firebase console)")
    print("  • Firebase API key (from Firebase console → Settings → Your apps)")
    print("  • Cloud Storage bucket name (from Firebase console → Storage)")
    print("  • AWS credentials (access key, secret key)")
    print("  • SSH key path for EC2 access")

    # Gather Firebase credentials
    print_header("Step 1: Firebase Configuration")

    firebase_project = get_input_with_validation(
        "Firebase Project ID: ",
        validator=validate_project_id
    )

    firebase_api_key = get_input_with_validation(
        "Firebase API Key: ",
        validator=validate_api_key
    )

    firebase_bucket = get_input_with_validation(
        "Cloud Storage Bucket (e.g., my-project.appspot.com): ",
        validator=validate_bucket
    )

    firebase_messaging_sender_id = get_input_with_validation(
        "Firebase Messaging Sender ID (from Firebase console → Settings): "
    )

    firebase_app_id = get_input_with_validation(
        "Firebase App ID (from Firebase console → Settings): "
    )

    # Gather AWS credentials
    print_header("Step 2: AWS Configuration")

    aws_access_key = get_input_with_validation(
        "AWS Access Key: "
    )

    aws_secret_key = get_input_with_validation(
        "AWS Secret Access Key: ",
        is_password=True
    )

    aws_region = input("AWS Region [ap-south-1]: ").strip() or "ap-south-1"

    # Gather EC2 SSH configuration
    print_header("Step 3: EC2 SSH Configuration")

    ssh_key_path = get_input_with_validation(
        "Path to SSH private key (e.g., C:\\Users\\you\\.ssh\\id_rsa): "
    )

    # Dashboard password
    print_header("Step 4: Dashboard Password")

    dashboard_password = get_input_with_validation(
        "Set a password for the dashboard: ",
        is_password=True
    )

    confirm_password = get_input_with_validation(
        "Confirm password: ",
        is_password=True
    )

    if dashboard_password != confirm_password:
        print_error("Passwords do not match")
        sys.exit(1)

    # Hash the password
    password_hash = hashlib.sha256(dashboard_password.encode()).hexdigest()

    # Summary and confirmation
    print_header("Configuration Summary")

    print(f"Firebase Project:    {firebase_project}")
    print(f"Storage Bucket:      {firebase_bucket}")
    print(f"AWS Region:          {aws_region}")
    print(f"SSH Key Path:        {ssh_key_path}")
    print(f"Dashboard Password:  {'*' * len(dashboard_password)}")

    confirmation = input("\n✓ Continue with setup? (yes/no): ").strip().lower()
    if confirmation not in ["yes", "y"]:
        print_warning("Setup cancelled")
        sys.exit(0)

    # Execute setup
    print_header("Setting Up Firebase")

    # 1. Create .env file
    print("\n1️⃣  Creating .env file...")
    create_env_file(firebase_project, firebase_api_key, firebase_bucket,
                   aws_access_key, aws_secret_key, ssh_key_path, aws_region)

    # 2. Update .firebaserc
    print("\n2️⃣  Updating .firebaserc...")
    update_firebaserc(firebase_project)

    # 3. Update dashboard config
    print("\n3️⃣  Updating dashboard Firebase config...")
    if not update_dashboard_config(firebase_project, firebase_api_key,
                                  firebase_messaging_sender_id, firebase_app_id):
        print_warning("Could not update dashboard config automatically")
        print("  → Update dashboard/index.html firebaseConfig manually")

    # 4. Create Firestore _config/access document
    print("\n4️⃣  Creating Firestore _config/access document...")
    if not create_firestore_config(firebase_project, firebase_api_key, password_hash):
        print_warning("Could not create Firestore document automatically")
        print("  → Create it manually in Firebase console:")
        print(f"    Collection: _config, Document: access, Field: passwordHash = {password_hash}")

    # 5. Deploy Firebase rules
    print("\n5️⃣  Deploying Firebase rules...")
    if not deploy_firebase_rules(firebase_project):
        print_warning("Could not deploy rules automatically")
        print("  → Deploy manually with: firebase deploy --project " + firebase_project)

    # 6. Deploy Firebase Hosting
    print("\n6️⃣  Deploying Firebase Hosting...")
    if not deploy_firebase_hosting(firebase_project):
        print_warning("Could not deploy hosting automatically")
        print("  → Deploy manually with: firebase deploy --project " + firebase_project)

    # Completion
    print_header("Setup Complete!")

    print("Next steps:")
    print(f"  1. Update EC2_INSTANCES in aws_study.py with your instance IDs")
    print(f"  2. Run your first simulation: python orchestrator/aws_study.py <stl_folder>")
    print(f"  3. Monitor in the dashboard at your Firebase Hosting URL")
    print("\nFor troubleshooting, see README.md → Troubleshooting")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_warning("\nSetup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
