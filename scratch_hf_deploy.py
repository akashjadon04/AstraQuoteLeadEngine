import os
import sys
from huggingface_hub import HfApi, create_repo

os.environ["HF_HOME"] = r"C:\Users\Akash\.cache\huggingface"

api = HfApi()

user_info = api.whoami()
username = user_info.get("name", "akashjadon04")
repo_id = f"{username}/astraquote-leadengine"

print(f"Logged in as: {username}")
print(f"Target Space: {repo_id}")

try:
    url = create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="static",
        private=False,
        exist_ok=True
    )
    print(f"Space repo created/verified successfully!")
except Exception as e:
    print(f"Create repo info: {e}")

print("Uploading files to Hugging Face Space...")
api.upload_folder(
    folder_path=r"C:\Users\Akash\Documents\AstraQuoteLeadEngine",
    repo_id=repo_id,
    repo_type="space",
    ignore_patterns=["venv/*", ".git/*", "__pycache__/*", "*.pyc", "data/*.log"]
)

print("\nSUCCESS! Static Space deployed and unpaused.")
print(f"Space URL: https://huggingface.co/spaces/{repo_id}")
print(f"Direct App URL: https://{username}-astraquote-leadengine.static.hf.space")
