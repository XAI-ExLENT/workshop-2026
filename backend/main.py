from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import datetime
import csv
import io
import re
import base64
import requests
import os
from dotenv import load_dotenv


# =========================================================
# Load environment variables from .env
# =========================================================

load_dotenv()


# =========================================================
# GitHub configuration
# =========================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")


# Make sure all GitHub settings exist
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN is missing from .env")

if not GITHUB_OWNER:
    raise RuntimeError("GITHUB_OWNER is missing from .env")

if not GITHUB_REPO:
    raise RuntimeError("GITHUB_REPO is missing from .env")


# GitHub API base URL
GITHUB_API_URL = (
    f"https://api.github.com/repos/"
    f"{GITHUB_OWNER}/{GITHUB_REPO}/contents"
)


# GitHub request headers
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# =========================================================
# Create FastAPI application
# =========================================================

app = FastAPI()


# =========================================================
# Allow frontend to communicate with FastAPI
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Local folders
# =========================================================

# Get the main project folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Get the main project folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Store submissions at the project root
SUBMISSIONS_FOLDER = PROJECT_ROOT / "Submissions"
SUBMISSIONS_FOLDER.mkdir(exist_ok=True)

# Store registration data at the project root
DATA_FOLDER = PROJECT_ROOT / "data"
DATA_FOLDER.mkdir(exist_ok=True)

REGISTRATION_FILE = DATA_FOLDER / "registrations.csv"


# =========================================================
# Settings
# =========================================================

MAX_FILE_SIZE = 40 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt"
}

ALLOWED_STUDENT_STATUS = {
    "Graduate",
    "Undergraduate"
}


# =========================================================
# Test endpoint
# =========================================================

@app.get("/")
def home():
    return {
        "message": "XAI Workshop backend is running!"
    }


# =========================================================
# Check whether a file already exists on GitHub
# =========================================================

def github_file_exists(github_path):
    """
    Check whether a file already exists in GitHub.

    Returns:
        True  -> file exists
        False -> file does not exist
    """

    url = f"{GITHUB_API_URL}/{github_path}"

    response = requests.get(
        url,
        headers=GITHUB_HEADERS,
        params={"ref": GITHUB_BRANCH}
    )

    if response.status_code == 200:
        return True

    if response.status_code == 404:
        return False

    raise Exception(
        f"GitHub check failed: "
        f"{response.status_code} {response.text}"
    )


# =========================================================
# Find an available filename
# =========================================================

def get_unique_filename(base_name, extension):
    """
    Creates a filename that does not already exist
    locally or on GitHub.

    Example:

    Priya_Deshmukh.pdf
    Priya_Deshmukh_2.pdf
    Priya_Deshmukh_3.pdf
    """

    counter = 1

    while True:

        if counter == 1:
            filename = (
                f"{base_name}{extension}"
            )
        else:
            filename = (
                f"{base_name}_{counter}{extension}"
            )

        local_path = SUBMISSIONS_FOLDER / filename

        github_path = (
            f"Submissions/{filename}"
        )

        # Check both local computer and GitHub
        local_exists = local_path.exists()
        github_exists = github_file_exists(
            github_path
        )

        if not local_exists and not github_exists:
            return filename

        counter += 1


# =========================================================
# Upload a file to GitHub
# =========================================================

def upload_file_to_github(
    github_path,
    file_contents,
    commit_message
):
    """
    Upload a new file to GitHub.

    GitHub requires the file contents to be
    Base64 encoded.
    """

    url = f"{GITHUB_API_URL}/{github_path}"

    encoded_content = base64.b64encode(
        file_contents
    ).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": GITHUB_BRANCH
    }

    response = requests.put(
        url,
        headers=GITHUB_HEADERS,
        json=payload
    )

    if response.status_code not in [200, 201]:

        raise Exception(
            f"GitHub file upload failed: "
            f"{response.status_code} "
            f"{response.text}"
        )

    return response.json()


# =========================================================
# Get registrations.csv from GitHub
# =========================================================

def get_github_csv():
    """
    Gets the existing registrations.csv from GitHub.

    Returns:
        csv_text
        sha
    """

    github_path = "data/registrations.csv"

    url = f"{GITHUB_API_URL}/{github_path}"

    response = requests.get(
        url,
        headers=GITHUB_HEADERS,
        params={"ref": GITHUB_BRANCH}
    )

    # CSV does not exist yet
    if response.status_code == 404:

        return None, None

    if response.status_code != 200:

        raise Exception(
            f"Could not read registrations.csv: "
            f"{response.status_code} "
            f"{response.text}"
        )

    data = response.json()

    encoded_content = data["content"]

    csv_bytes = base64.b64decode(
        encoded_content
    )

    csv_text = csv_bytes.decode(
        "utf-8"
    )

    sha = data["sha"]

    return csv_text, sha


# =========================================================
# Update registrations.csv on GitHub
# =========================================================

def update_github_csv(
    csv_text,
    sha,
    commit_message
):
    """
    Creates or updates registrations.csv
    on GitHub.
    """

    github_path = "data/registrations.csv"

    url = f"{GITHUB_API_URL}/{github_path}"

    csv_bytes = csv_text.encode(
        "utf-8"
    )

    encoded_content = base64.b64encode(
        csv_bytes
    ).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": GITHUB_BRANCH
    }

    # If CSV already exists, GitHub requires SHA
    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=GITHUB_HEADERS,
        json=payload
    )

    if response.status_code not in [200, 201]:

        raise Exception(
            f"GitHub CSV update failed: "
            f"{response.status_code} "
            f"{response.text}"
        )

    return response.json()


# =========================================================
# Registration endpoint
# =========================================================

@app.post("/submit_registration")
async def submit_registration(
    full_name: str = Form(...),
    email: str = Form(...),
    student_status: str = Form(...),
    university_affiliation: str = Form(...),
    file: UploadFile = File(...)
):

    # -----------------------------------------------------
    # 1. Validate name
    # -----------------------------------------------------

    full_name = full_name.strip()

    if not full_name:

        raise HTTPException(
            status_code=400,
            detail="Name is required."
        )


    # -----------------------------------------------------
    # 2. Validate email
    # -----------------------------------------------------

    email = email.strip()

    if not email:

        raise HTTPException(
            status_code=400,
            detail="Email is required."
        )

    email_pattern = (
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    if not re.match(
        email_pattern,
        email
    ):

        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address."
        )


    # -----------------------------------------------------
    # 3. Validate student status
    # -----------------------------------------------------

    if student_status not in ALLOWED_STUDENT_STATUS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Please select Graduate "
                "or Undergraduate."
            )
        )


    # -----------------------------------------------------
    # 4. Validate university
    # -----------------------------------------------------

    university_affiliation = (
        university_affiliation.strip()
    )

    if not university_affiliation:

        raise HTTPException(
            status_code=400,
            detail=(
                "University affiliation is required."
            )
        )


    # -----------------------------------------------------
    # 5. Validate file
    # -----------------------------------------------------

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail=(
                "Please upload a PDF or TXT file."
            )
        )

    original_extension = (
        Path(file.filename)
        .suffix
        .lower()
    )

    if original_extension not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Only PDF and TXT files are allowed."
            )
        )


    # -----------------------------------------------------
    # 6. Read file
    # -----------------------------------------------------

    try:

        file_contents = await file.read()

    except Exception:

        raise HTTPException(
            status_code=500,
            detail="Could not read the uploaded file."
        )


    # -----------------------------------------------------
    # 7. Check file size
    # -----------------------------------------------------

    file_size = len(file_contents)

    if file_size > MAX_FILE_SIZE:

        raise HTTPException(
            status_code=400,
            detail=(
                "File is too large. "
                "Maximum file size is 40 MB."
            )
        )


    # -----------------------------------------------------
    # 8. Create safe name
    # -----------------------------------------------------

    clean_name = full_name.replace(
        " ",
        "_"
    )

    clean_name = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        clean_name
    )

    if not clean_name:

        raise HTTPException(
            status_code=400,
            detail="Please enter a valid name."
        )


    # -----------------------------------------------------
    # 9. Create unique filename
    # -----------------------------------------------------

    try:

        new_filename = get_unique_filename(
            clean_name,
            original_extension
        )

    except Exception as error:

        print(error)

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not check GitHub "
                "for an available filename."
            )
        )


    # -----------------------------------------------------
    # 10. Save file locally first
    # -----------------------------------------------------

    local_file_path = (
        SUBMISSIONS_FOLDER /
        new_filename
    )

    try:

        with open(
            local_file_path,
            "wb"
        ) as saved_file:

            saved_file.write(
                file_contents
            )

    except Exception:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not save the uploaded file."
            )
        )


    # -----------------------------------------------------
    # 11. Create submission date
    # -----------------------------------------------------

    submission_date = (
        datetime.now()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


    # -----------------------------------------------------
    # 12. Upload file to GitHub
    # -----------------------------------------------------

    github_file_path = (
        f"Submissions/{new_filename}"
    )

    try:

        upload_file_to_github(
            github_file_path,
            file_contents,
            (
                f"Add workshop submission: "
                f"{new_filename}"
            )
        )

    except Exception as error:

        print(error)

        # Remove local file if GitHub upload fails
        if local_file_path.exists():
            local_file_path.unlink()

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not upload the submission "
                "to GitHub."
            )
        )


    # -----------------------------------------------------
    # 13. Get existing CSV from GitHub
    # -----------------------------------------------------

    try:

        existing_csv, csv_sha = (
            get_github_csv()
        )

    except Exception as error:

        print(error)

        raise HTTPException(
            status_code=500,
            detail=(
                "The submission file was uploaded, "
                "but the registration CSV could "
                "not be read from GitHub."
            )
        )


    # -----------------------------------------------------
    # 14. Add registration to CSV
    # -----------------------------------------------------

    try:

        output = io.StringIO(
            newline=""
        )

        writer = csv.writer(
            output
        )

        # CSV doesn't exist yet
        if existing_csv is None:

            writer.writerow([
                "Name",
                "Email",
                "Student Status",
                "University Affiliation",
                "File",
                "Submission Date"
            ])

        else:

            # Copy existing CSV rows
            existing_reader = csv.reader(
                io.StringIO(existing_csv)
            )

            for row in existing_reader:
                writer.writerow(row)


        # Add new registration
        writer.writerow([
            full_name,
            email,
            student_status,
            university_affiliation,
            github_file_path,
            submission_date
        ])

        new_csv = output.getvalue()

    except Exception as error:

        print(error)

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not create the "
                "registration CSV."
            )
        )


    # -----------------------------------------------------
    # 15. Update CSV on GitHub
    # -----------------------------------------------------

    try:

        update_github_csv(
            new_csv,
            csv_sha,
            (
                "Update workshop registrations"
            )
        )

    except Exception as error:

        print(error)

        raise HTTPException(
            status_code=500,
            detail=(
                "The submission file was uploaded, "
                "but the registration CSV could "
                "not be updated."
            )
        )


    # -----------------------------------------------------
    # 16. Also save/update local CSV
    # -----------------------------------------------------

    try:

        with open(
            REGISTRATION_FILE,
            "w",
            newline="",
            encoding="utf-8"
        ) as local_csv:

            local_csv.write(
                new_csv
            )

    except Exception as error:

        print(
            "Warning: local CSV could not be updated."
        )


    # -----------------------------------------------------
    # 17. Return success
    # -----------------------------------------------------

    return {
        "message": (
            "Registration submitted successfully!"
        ),
        "file": github_file_path,
        "submission_date": submission_date
    }