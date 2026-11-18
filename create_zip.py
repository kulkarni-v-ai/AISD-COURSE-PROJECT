import os
import zipfile
import shutil
from pathlib import Path


def make_zip():
    source_dir = Path(r"c:\Users\ariha\Documents\aisd").resolve()
    zip_destinations = [
        Path(r"c:\Users\ariha\Documents\AISD_PROJECT.zip"),
        Path(r"C:\Users\ariha\Desktop\AISD_PROJECT.zip"),
        Path(r"C:\Users\ariha\Desktop\AISD\AISD_PROJECT.zip"),
    ]

    primary_zip = zip_destinations[0]
    print(f"Creating ZIP archive at {primary_zip}...")

    exclude_dirs = {
        "node_modules", ".next", "__pycache__", ".pytest_cache", ".git"
    }
    exclude_extensions = {".pyc", ".pyo", ".log"}
    exclude_files = {"aisd.db", "agent_local.db", "agent_offline.db"}

    total_files = 0
    with zipfile.ZipFile(primary_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in exclude_extensions or file in exclude_files:
                    continue
                
                full_path = Path(root) / file
                rel_path = full_path.relative_to(source_dir.parent) # keeps 'aisd/...' as top folder
                zipf.write(full_path, rel_path)
                total_files += 1

    file_size_mb = round(os.path.getsize(primary_zip) / (1024 * 1024), 2)
    print(f"ZIP created successfully with {total_files} files ({file_size_mb} MB).")

    # Copy to Desktop locations
    for dest in zip_destinations[1:]:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(primary_zip, dest)
            print(f"Copied to: {dest}")
        except Exception as e:
            print(f"Could not copy to {dest}: {e}")

    # Copy the docx guide to Desktop locations
    docx_src = source_dir / "AISD_TEAM_RUN_GUIDE.docx"
    if docx_src.exists():
        docx_destinations = [
            Path(r"C:\Users\ariha\Desktop\AISD_TEAM_RUN_GUIDE.docx"),
            Path(r"C:\Users\ariha\Desktop\AISD\AISD_TEAM_RUN_GUIDE.docx"),
        ]
        for d in docx_destinations:
            try:
                shutil.copy2(docx_src, d)
                print(f"Copied Word Run Guide to: {d}")
            except Exception as e:
                print(f"Could not copy docx to {d}: {e}")


if __name__ == "__main__":
    make_zip()
