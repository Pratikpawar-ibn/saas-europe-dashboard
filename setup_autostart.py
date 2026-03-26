#!/usr/bin/env python3
"""
setup_autostart.py
------------------
Registers start.py in Windows Task Scheduler so the dashboard
starts automatically at every Windows login -- silently, no popup.

Uses PowerShell New-ScheduledTask (handles paths with spaces reliably).
Run once:  python setup_autostart.py
"""

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR     = Path(__file__).parent
PYTHON_EXE   = sys.executable
START_SCRIPT = BASE_DIR / "start.py"
TASK_NAME    = "SaaS_Europe_Dashboard"
VBS_FILE     = BASE_DIR / "run_silent.vbs"


def create_vbs_launcher():
    """Create a VBScript that runs start.py with no console window."""
    vbs = (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run Chr(34) & "{PYTHON_EXE}" & Chr(34) & " " & Chr(34) & "{START_SCRIPT}" & Chr(34), 0, False\r\n'
    )
    VBS_FILE.write_text(vbs, encoding="utf-8")
    print(f"[Setup] Created silent launcher: {VBS_FILE.name}")


def register_task():
    """Use PowerShell to register the scheduled task (handles spaces in paths)."""
    vbs_escaped = str(VBS_FILE).replace("'", "''")

    ps_script = f"""
$action  = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '"{vbs_escaped}"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
Write-Output "REGISTERED"
"""

    print(f"[Setup] Registering task: {TASK_NAME}")
    result = subprocess.run(
        ["powershell.exe", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True,
    )

    if "REGISTERED" in result.stdout or result.returncode == 0:
        print(f"[Setup] SUCCESS: Task '{TASK_NAME}' registered.")
        print("[Setup] Dashboard will start automatically at every Windows login.")
    else:
        print(f"[Setup] FAILED (exit code {result.returncode})")
        if result.stderr:
            print(f"[Setup] Error: {result.stderr.strip()}")
        if result.stdout:
            print(f"[Setup] Output: {result.stdout.strip()}")
        print("[Setup] TIP: Run as Administrator for HIGHEST privilege level.")


def verify_task():
    """Print task summary from Task Scheduler."""
    result = subprocess.run(
        ["powershell.exe", "-NonInteractive", "-Command",
         f"Get-ScheduledTask -TaskName '{TASK_NAME}' | Select-Object TaskName,State | Format-List"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        print("\n[Setup] Task verification:")
        for line in result.stdout.strip().splitlines():
            print(f"         {line}")
    else:
        print("[Setup] Could not verify -- may need to check Task Scheduler manually.")


if __name__ == "__main__":
    print("=" * 58)
    print("  SaaS Europe Dashboard -- Windows Autostart Setup")
    print("=" * 58)
    print(f"  Python : {PYTHON_EXE}")
    print(f"  Script : {START_SCRIPT.name}")
    print(f"  Task   : {TASK_NAME}")
    print()

    if not START_SCRIPT.exists():
        print(f"[Setup] ERROR: start.py not found at {START_SCRIPT}")
        sys.exit(1)

    create_vbs_launcher()
    register_task()
    verify_task()

    print()
    print(f"[Setup] Done. To remove the task:")
    print(f'         schtasks /Delete /TN "{TASK_NAME}" /F')
