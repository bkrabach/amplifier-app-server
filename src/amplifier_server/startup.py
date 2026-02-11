"""Linux systemd service management for Cortex Server.

Provides functionality to:
- Install/uninstall as a user systemd service
- Start/stop/restart the service
- Check status and view logs
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SERVICE_NAME = "cortex-server"


def get_service_file_path() -> Path:
    """Get the path where the user systemd service file should be installed."""
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"


def get_venv_path() -> Path:
    """Get the path to the virtual environment."""
    # Try to find it from the current executable
    venv = Path(sys.executable).parent.parent
    if (venv / "bin" / "amplifier-server").exists():
        return venv
    # Fall back to the repo's .venv
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / ".venv"


def get_working_dir() -> Path:
    """Get the working directory (repo root)."""
    return Path(__file__).parent.parent.parent


def is_installed() -> bool:
    """Check if the systemd service is installed."""
    return get_service_file_path().exists()


def get_status() -> dict:
    """Get detailed status of the service."""
    if not is_installed():
        return {"installed": False}

    try:
        result = subprocess.run(
            ["systemctl", "--user", "status", SERVICE_NAME],
            capture_output=True,
            text=True,
        )

        status = {
            "installed": True,
            "raw": result.stdout,
            "running": "Active: active (running)" in result.stdout,
        }

        # Parse key fields
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Active:"):
                status["active"] = line.split("Active:")[1].strip()
            elif line.startswith("Main PID:"):
                status["pid"] = line.split("Main PID:")[1].strip().split()[0]

        return status
    except Exception as e:
        return {"installed": True, "error": str(e)}


def install(
    port: int = 19420,
    env_file: Path | None = None,
) -> bool:
    """Install Cortex Server as a user systemd service.

    Args:
        port: Port to run the server on
        env_file: Optional path to environment file with API keys etc.

    Returns:
        True if installation succeeded
    """
    venv = get_venv_path()
    working_dir = get_working_dir()

    if not (venv / "bin" / "amplifier-server").exists():
        logger.error(f"amplifier-server not found in {venv}/bin/")
        logger.error("Make sure you've installed the package: uv pip install -e .")
        return False

    # Build environment file path
    if env_file is None:
        env_file = Path.home() / ".cortex" / "server.env"

    # Create the service file content
    # Include common paths where tools like uv might be installed
    path_dirs = [
        f"{venv}/bin",
        str(Path.home() / ".local/bin"),
        str(Path.home() / ".cargo/bin"),
        "/snap/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    path_env = ":".join(path_dirs)

    home_dir = Path.home()

    service_content = f"""[Unit]
Description=Cortex Server - AI-powered notification and attention management
Documentation=https://github.com/bkrabach/amplifier-app-server
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
Environment="PATH={path_env}"
Environment="HOME={home_dir}"
Environment="USER={os.environ.get("USER", "")}"
"""

    if env_file.exists():
        service_content += f"EnvironmentFile={env_file}\n"

    service_content += f"""ExecStart={venv}/bin/amplifier-server run --port {port}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""

    # Create the directory if needed
    service_path = get_service_file_path()
    service_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the service file
    service_path.write_text(service_content)
    logger.info(f"Created service file: {service_path}")

    # Reload systemd
    result = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Failed to reload systemd: {result.stderr}")
        return False

    # Enable the service (start on login)
    result = subprocess.run(
        ["systemctl", "--user", "enable", SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Failed to enable service: {result.stderr}")
        return False

    # Enable lingering so service runs even when not logged in
    result = subprocess.run(
        ["loginctl", "enable-linger", os.environ.get("USER", "")],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(f"Failed to enable linger (service may stop on logout): {result.stderr}")

    logger.info(f"Installed and enabled {SERVICE_NAME}")
    return True


def uninstall() -> bool:
    """Remove the Cortex Server systemd service.

    Returns:
        True if uninstallation succeeded
    """
    if not is_installed():
        logger.info("Service not installed, nothing to remove")
        return True

    # Stop the service if running
    stop()

    # Disable the service
    subprocess.run(
        ["systemctl", "--user", "disable", SERVICE_NAME],
        capture_output=True,
        text=True,
    )

    # Remove the service file
    service_path = get_service_file_path()
    service_path.unlink(missing_ok=True)
    logger.info(f"Removed service file: {service_path}")

    # Reload systemd
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )

    logger.info(f"Uninstalled {SERVICE_NAME}")
    return True


def start() -> bool:
    """Start the service."""
    if not is_installed():
        logger.error("Service not installed. Run 'install' first.")
        return False

    result = subprocess.run(
        ["systemctl", "--user", "start", SERVICE_NAME],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info(f"Started {SERVICE_NAME}")
        return True
    else:
        logger.error(f"Failed to start: {result.stderr}")
        return False


def stop() -> bool:
    """Stop the service."""
    if not is_installed():
        return True

    result = subprocess.run(
        ["systemctl", "--user", "stop", SERVICE_NAME],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info(f"Stopped {SERVICE_NAME}")
        return True
    else:
        logger.error(f"Failed to stop: {result.stderr}")
        return False


def restart() -> bool:
    """Restart the service."""
    if not is_installed():
        logger.error("Service not installed. Run 'install' first.")
        return False

    result = subprocess.run(
        ["systemctl", "--user", "restart", SERVICE_NAME],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        logger.info(f"Restarted {SERVICE_NAME}")
        return True
    else:
        logger.error(f"Failed to restart: {result.stderr}")
        return False


def logs(follow: bool = False, lines: int = 50) -> str | None:
    """Get service logs.

    Args:
        follow: If True, follow logs (like tail -f)
        lines: Number of lines to show

    Returns:
        Log output if not following, None if following (streams to stdout)
    """
    cmd = ["journalctl", "--user", "-u", SERVICE_NAME, "-n", str(lines)]

    if follow:
        cmd.append("-f")
        # Stream directly to stdout
        subprocess.run(cmd)
        return None
    else:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout
