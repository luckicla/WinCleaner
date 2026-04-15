"""
Profile management: save, load, list, delete, import/export profiles.
"""
import json
import os
import shutil
from datetime import datetime
from core.data import PRESET_PROFILES

PROFILES_DIR = os.path.join(os.path.expanduser("~"), ".winclean", "profiles")


def ensure_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


def get_profile_path(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in (" ", "_", "-")).rstrip()
    return os.path.join(PROFILES_DIR, f"{safe}.json")


def list_profiles() -> list[dict]:
    ensure_dir()
    profiles = []

    # Built-in presets first
    for key, data in PRESET_PROFILES.items():
        profiles.append({
            "id": key,
            "name": data["name"],
            "description": data["description"],
            "preset": True,
            "path": None,
        })

    # User profiles
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(PROFILES_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profiles.append({
                    "id": fname.replace(".json", ""),
                    "name": data.get("name", fname.replace(".json", "")),
                    "description": data.get("description", "Perfil de usuario"),
                    "preset": False,
                    "path": path,
                    "created": data.get("created", ""),
                    "modified": data.get("modified", ""),
                })
            except Exception:
                pass
    return profiles


def load_profile(profile_id: str) -> dict | None:
    # Check presets first
    if profile_id in PRESET_PROFILES:
        return PRESET_PROFILES[profile_id]

    # Check user profiles
    ensure_dir()
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith(".json"):
            pid = fname.replace(".json", "")
            if pid == profile_id:
                path = os.path.join(PROFILES_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
    return None


def save_profile(name: str, description: str, apps: list, services: list, tweaks: list) -> str:
    ensure_dir()
    path = get_profile_path(name)
    now = datetime.now().isoformat(timespec="seconds")

    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    data = {
        "name": name,
        "description": description,
        "apps": apps,
        "services": services,
        "tweaks": tweaks,
        "created": existing.get("created", now),
        "modified": now,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def delete_profile(profile_id: str) -> bool:
    ensure_dir()
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith(".json") and fname.replace(".json", "") == profile_id:
            os.remove(os.path.join(PROFILES_DIR, fname))
            return True
    return False


def import_profile(src_path: str) -> str:
    ensure_dir()
    with open(src_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("name", os.path.basename(src_path).replace(".json", ""))
    dst = get_profile_path(name)
    shutil.copy2(src_path, dst)
    return name


def export_profile(profile_id: str, dst_path: str) -> bool:
    profile = load_profile(profile_id)
    if not profile:
        return False
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return True
