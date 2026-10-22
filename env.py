"""Load KEY=VALUE settings from .env next to the code. Variables already set in the environment win."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), os.path.expanduser(value))


def set_env_value(key: str, value: str, path: Path = ENV_FILE) -> None:
    """Set KEY=value in the .env file (replacing an existing line) and in this process's environment."""
    lines = path.read_text().splitlines() if path.exists() else []
    pattern = f"{key}="
    replaced = [f"{key}={value}" if line.strip().startswith(pattern) else line for line in lines]
    if replaced == lines and f"{key}={value}" not in lines:
        replaced.append(f"{key}={value}")
    path.write_text("\n".join(replaced) + "\n")
    os.environ[key] = value
