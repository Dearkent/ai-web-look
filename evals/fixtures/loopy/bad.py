import subprocess
def wait_ready(check):
    while not check():
        pass
subprocess.run(["git", "grep", "-n", "Stuck", "HEAD"])
