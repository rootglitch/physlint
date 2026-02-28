"""
First-run bootstrap for Isaac Sim pip install.
Run once from Windows to download all required Kit extensions from Nucleus.

  python _isaacsim_first_run.py

This downloads omni.replicator.core and other extensions to
isaacsim/extscache/ (~2-5 GB). Subsequent runs use the local cache.
"""
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
