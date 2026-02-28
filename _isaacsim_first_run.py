"""
First-run bootstrap for Isaac Sim pip install.
Run once from Windows to download all required Kit extensions from Nucleus.

  python _isaacsim_first_run.py

This downloads omni.replicator.core and other extensions (~2-5 GB on first run).
Subsequent runs use the local cache at C:/Users/<user>/AppData/Local/ov/data/exts/
"""
import os
import sys

# Add PyTorch DLL directory to PATH before Kit boots.
# Kit's C++ extension loader uses Win32 LoadLibrary which only searches PATH — not
# os.add_dll_directory. Without this, loading any extension that depends on torch
# (omni.isaac.core, isaacsim.replicator.writers, etc.) fails with WinError 1114
# even when torch itself imports fine.
_torch_lib = os.path.join(
    os.path.dirname(sys.executable),
    "Lib", "site-packages", "torch", "lib",
)
if os.path.isdir(_torch_lib):
    os.environ["PATH"] = _torch_lib + ";" + os.environ.get("PATH", "")
    os.add_dll_directory(_torch_lib)

os.environ["OMNI_KIT_ACCEPT_EULA"] = "yes"

from isaacsim import SimulationApp

print("[first_run] Starting Isaac Sim (this downloads extensions on first run)...")
kit = SimulationApp({
    "headless":  True,
    "renderer":  "RaytracedLighting",
})

print("[first_run] Kit started. Importing omni.replicator...")
import omni.replicator.core as rep
import omni.usd

print("[first_run] omni.replicator.core loaded successfully.")
print("[first_run] Extensions are now cached. Future runs will be fast.")

kit.close()
print("[first_run] Done.")
