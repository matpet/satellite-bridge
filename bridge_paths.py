"""Keep user data outside the signed app bundle, across app replacements."""

import fcntl
import os
from pathlib import Path


RESOURCE_ROOT = Path(__file__).resolve().parent


def data_directory():
    override = os.environ.get("SATELLITE_BRIDGE_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / "Library" / "Application Support" / "Satellite Bridge"


def prepare_data(directory=None, seed_directory=None):
    directory = Path(directory) if directory is not None else data_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    seed = (Path(seed_directory) if seed_directory is not None else RESOURCE_ROOT) / "bridge-settings.json"
    target = directory / "bridge-settings.json"
    if seed.exists() and seed.resolve() != target.resolve():
        # First launch imports the existing pairs. Never replace later edits.
        original = seed.read_text(encoding="utf-8")
        try:
            with target.open("x", encoding="utf-8") as output:
                output.write(original)
        except FileExistsError:
            pass
    return directory


def instance_lock(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (directory / ".instance.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock
