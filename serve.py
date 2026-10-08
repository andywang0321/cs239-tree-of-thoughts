"""Start Ollama without root, keep it running, pull the models, verify the GPU is in use.

    uv run serve.py --check        # report what is installed, running, and on which device
    uv run serve.py --install      # download the ollama binary from GitHub into ~/bin (no root)
    uv run serve.py --pull         # download the two 2023 models into ~/ollama-models
    uv run serve.py                # start the server in the foreground (Ctrl-C to stop)
    uv run serve.py --gpu          # is the model on the GPU, or silently on the CPU?
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

import llm  # noqa: F401  - imports the resolved OLLAMA_BIN path
from llm import OLLAMA_BIN

HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
MODELS_DIR = os.environ.get("OLLAMA_MODELS", os.path.expanduser("~/ollama-models"))
BIN_DIR = os.environ.get("OLLAMA_BIN_DIR", os.path.expanduser("~/bin"))
TAGS = ["llama2:7b-chat", "mistral:7b-instruct"]
RELEASES = "https://api.github.com/repos/ollama/ollama/releases/latest"


def api(path):
    with urllib.request.urlopen(f"http://{HOST}{path}", timeout=5) as r:
        return json.load(r)


def asset_name():
    """Current Linux assets are ollama-linux-<arch>-<variant>.tar.zst (CUDA is in the default
    amd64 build; there is a separate -rocm one). The old ...-amd64.tgz is gone, hence the 404."""
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine().lower())
    if not arch:
        sys.exit(f"unsupported architecture: {platform.machine()}")
    variant = os.environ.get("OLLAMA_VARIANT", "")
    suffix = f"-{variant}" if variant else ""
    return arch, f"ollama-linux-{arch}{suffix}.tar.zst"


def release_assets():
    with urllib.request.urlopen(RELEASES, timeout=30) as r:
        data = json.load(r)
    return data["tag_name"], {a["name"]: a["browser_download_url"] for a in data["assets"]}


def fetch(url, dest):
    """Stream to disk with a progress line, so a 1.4 GB download is visibly alive."""
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, t0 = 0, time.time()
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r  {got / 1e6:6.0f}/{total / 1e6:.0f} MB "
                      f"({got / max(time.time() - t0, .1) / 1e6:.1f} MB/s)", end="", flush=True)
    print()


def install():
    """Download the binary and unpack it into ~/bin. Needs no privileges at all."""
    arch, asset = asset_name()
    tag, assets = release_assets()
    if asset not in assets:
        sys.exit(f"{asset} not in release {tag}. Available:\n  " + "\n  ".join(
            n for n in assets if n.startswith("ollama-linux")))
    url = assets[asset]
    print(f"release {tag}\nasset   {asset}\nurl     {url}\n")
    os.makedirs(BIN_DIR, exist_ok=True)
    tmp = os.path.join(BIN_DIR, asset)
    print("downloading...")
    fetch(url, tmp)
    print(f"extracting into {BIN_DIR} (paths are lib/ollama/* and ./ollama)...")
    if not extract(tmp, BIN_DIR):
        sys.exit("could not extract .tar.zst - install zstd (conda/pip: `pip install zstandard`, "
                 "or `tar --zstd -xf` if your tar supports it)")
    os.remove(tmp)
    binary = os.path.join(BIN_DIR, "ollama")
    os.chmod(binary, 0o755)
    print(f"installed {binary} ({os.path.getsize(binary) / 1e6:.0f} MB)")
    ok, msg = check_exec(binary)
    print(f"exec check  : {'ok' if ok else 'FAILED - ' + msg}")
    if not ok:
        print("\nThe filesystem holding this directory probably has the noexec flag set. "
              "Check with:  findmnt -T ~/bin -o TARGET,SOURCE,OPTIONS\n"
              "Then either install somewhere else:\n"
              "    OLLAMA_BIN_DIR=/path/on/exec/mount uv run serve.py --install\n"
              "or look for a module/container with a writable exec mount (often /tmp or /scratch).")
        sys.exit(1)
    print(f"\nadd it to your PATH once:  export PATH=\"{BIN_DIR}:$PATH\"")
    print("then:  uv run serve.py        # start the server")


def check_exec(binary):
    """Distinguish 'file is not executable' from 'the mount forbids exec at all'."""
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
    except PermissionError as e:
        hint = "mount has noexec" if not _exec_allowed(BIN_DIR) else "permission denied"
        return False, f"{e} ({hint})"
    except OSError as e:
        return False, str(e)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


def _exec_allowed(path):
    """False when the filesystem is mounted noexec (Linux only; macOS has no ST_NOEXEC)."""
    flag = getattr(os, "ST_NOEXEC", 0)
    try:
        return not (os.statvfs(path).f_flag & flag) if flag else True
    except OSError:
        return True


def extract(path, dest):
    """tarfile handles .tar.zst only on Python 3.14+; fall back to the zstd CLI or tar --zstd."""
    try:
        with tarfile.open(path) as t:
            t.extractall(dest)
        return True
    except (tarfile.TarError, ValueError, NotImplementedError):
        pass
    for cmd in (["tar", "--zstd", "-xf", path, "-C", dest],
                ["unzstd", "-c", path], ["zstd", "-dc", path]):
        if not shutil.which(cmd[0]):
            continue
        try:
            if cmd[0] == "tar":
                if subprocess.run(cmd, capture_output=True).returncode == 0:
                    return True
            else:  # decompress to a temp .tar, then untar
                out = path + ".tar"
                with open(out, "wb") as f:
                    if subprocess.run(cmd, stdout=f, capture_output=True).returncode:
                        continue
                with tarfile.open(out) as t:
                    t.extractall(dest)
                os.remove(out)
                return True
        except (OSError, tarfile.TarError):
            continue
    if shutil.which("pip"):
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "zstandard"])
        try:
            with tarfile.open(path) as t:
                t.extractall(dest)
            return True
        except Exception:
            pass
    return False


def find_binary():
    return (shutil.which(OLLAMA_BIN) or (OLLAMA_BIN if os.path.exists(OLLAMA_BIN) else None)
            or (os.path.join(BIN_DIR, "ollama")
                if os.path.exists(os.path.join(BIN_DIR, "ollama")) else None))


def installed():
    """Report the binary, the model store, and whether a server is already answering."""
    found = find_binary()
    print(f"binary      : {found or 'NOT FOUND - run: uv run serve.py --install'}")
    if found:
        v = subprocess.run([found, "--version"], capture_output=True, text=True).stdout.strip()
        print(f"version     : {v or 'unknown'}")
    print(f"model store : {MODELS_DIR} ({'exists' if os.path.isdir(MODELS_DIR) else 'missing'})")
    print(f"endpoint    : http://{HOST}  (client default: {'same' if '11434' in HOST else 'MISMATCH'})")
    try:
        names = [m["name"] for m in api("/api/tags")["models"]]
        print(f"server      : running, {len(names)} models")
        for t in TAGS:
            print(f"  {'ok  ' if any(n.startswith(t) for n in names) else 'MISS'} {t}")
        try:  # only meaningful while something is loaded
            for m in api("/api/ps").get("models", []):
                print(f"  loaded: {m['name']} on {m.get('size_vram', 0) / 1e9:.1f} GB VRAM")
        except urllib.error.URLError:
            pass
    except (urllib.error.URLError, TimeoutError, OSError):
        print("server      : not running  (start it with: uv run serve.py)")


def start():
    found = find_binary()
    if not found:
        sys.exit(f"ollama binary not found (looked for {OLLAMA_BIN}). "
                 "Run `uv run serve.py --install` or set OLLAMA_BIN=/path/to/ollama.")
    os.makedirs(MODELS_DIR, exist_ok=True)
    env = {**os.environ, "OLLAMA_HOST": HOST, "OLLAMA_MODELS": MODELS_DIR}
    print(f"starting {found} on {HOST}, models in {MODELS_DIR}")
    print("keep this terminal open (or run it under tmux/nohup); Ctrl-C to stop")
    subprocess.run([found, "serve"], env=env)


def pull():
    found = find_binary() or OLLAMA_BIN
    env = {**os.environ, "OLLAMA_HOST": HOST, "OLLAMA_MODELS": MODELS_DIR, "OLLAMA_BIN": found}
    for tag in TAGS:
        print(f"pulling {tag} ...", flush=True)
        subprocess.run([found, "pull", tag], env=env)
    print("done; `uv run serve.py --check` to confirm")


def gpu_check():
    """The one check that matters: is the model on the GPU, or silently on the CPU?"""
    nv = shutil.which("nvidia-smi")
    if nv:
        out = subprocess.run([nv, "--query-gpu=name,memory.used,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True).stdout
        print(f"nvidia-smi  : {out.strip() or 'no GPU visible'}")
    else:
        print("nvidia-smi  : not found (CPU-only box?)")
    try:
        models = api("/api/ps").get("models", [])
    except Exception as e:
        sys.exit(f"server not reachable: {e}")
    if not models:
        print("ollama ps   : nothing loaded; run `ollama run llama2:7b-chat hi` then re-check")
    for m in models:
        vram, total = m.get("size_vram", 0), m.get("size", 1)
        verdict = "100% GPU" if vram >= total * 0.95 else f"only {vram / total:.0%} on GPU - SLOW"
        print(f"ollama ps   : {m['name']} -> {verdict}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report install/server/model status")
    ap.add_argument("--install", action="store_true", help="download the ollama binary into ~/bin")
    ap.add_argument("--pull", action="store_true", help="download both models")
    ap.add_argument("--gpu", action="store_true", help="verify GPU offload")
    a = ap.parse_args()
    if a.check:
        installed()
    elif a.install:
        install()
    elif a.pull:
        pull()
    elif a.gpu:
        gpu_check()
    else:
        start()


if __name__ == "__main__":
    main()
