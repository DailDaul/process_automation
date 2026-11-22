import subprocess
# Это вызовет предупреждение HIGH уровня у Bandit
subprocess.call("ls -la", shell=True)
