import os
import subprocess

folder = "esp32"
port = "COM5"

for filename in os.listdir(folder):
    if filename.endswith(".py") or filename.endswith(".json"):
        local_path = os.path.join(folder, filename)
        remote_path = f":/{filename}"
        subprocess.run(["mpremote", "connect", port, "fs", "cp", local_path, remote_path])