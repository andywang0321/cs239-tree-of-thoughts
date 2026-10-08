"""Start Ollama without root, keep it running, pull the models, verify the GPU is in use.

    uv run serve.py --check        # report what is installed, running, and on which device
    uv run serve.py --install      # download a release from GitHub into ~/ollama (no root)
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
# The archive is bin/ollama + lib/ollama/*, and the binary finds its CUDA libraries through
# $ORIGIN/../lib/ollama. So it must be unpacked intact and never flattened - hence its own prefix,
# with a symlink in BIN_DIR for PATH convenience.
PREFIX = os.environ.get("OLLAMA_PREFIX", os.path.expanduser("~/ollama"))
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
    """Download the release and unpack it intact into ~/ollama, no privileges needed."""
    arch, asset = asset_name()
    tag, assets = release_assets()
    if asset not in assets:
        sys.exit(f"{asset} not in release {tag}. Available:\n  " + "\n  ".join(
            n for n in assets if n.startswith("ollama-linux")))
    url = assets[asset]
    print(f"release {tag}\nasset   {asset}\nprefix  {PREFIX}\nurl     {url}\n")
    os.makedirs(PREFIX, exist_ok=True)
    tmp = os.path.join(PREFIX, asset)
    print("downloading...")
    fetch(url, tmp)
    print(f"extracting into {PREFIX} (keeps bin/ and lib/ together: the binary needs lib/ollama)")
    names = extract(tmp, PREFIX)
    if not names:
        sys.exit("extraction failed - install `zstandard` (pip) or `zstd` (system) and retry")
    binary = os.path.join(PREFIX, "bin", "ollama")
    if not os.path.isfile(binary):
        sys.exit(f"unexpected archive layout: {names[:5]} (no bin/ollama). "
                 "Report this - the release format changed again.")
    os.remove(tmp)
    os.chmod(binary, 0o755)
    print(f"installed {binary} ({os.path.getsize(binary) / 1e6:.0f} MB, "
          f"{len(names) - 1} support files)")
    ok, msg = check_exec(binary)
    print(f"exec check  : {'ok - ' + msg if ok else 'FAILED - ' + msg}")
    if not ok:
        if "Exec format error" in msg:
            print(f"\nThat means the wrong architecture was installed for this machine "
                  f"({platform.machine()}). Re-run with the matching asset, e.g. "
                  f"OLLAMA_VARIANT='' and check `uname -m`.")
        else:
            print("\nIf a stock binary fails here too, this filesystem is mounted noexec (common on "
                  "managed cluster homes). Check:  findmnt -T ~ -o TARGET,SOURCE,OPTIONS\n"
                  "Then install to an exec-capable mount instead:\n"
                  "    OLLAMA_PREFIX=/scratch/$USER/ollama uv run serve.py --install")
        sys.exit(1)
    os.makedirs(BIN_DIR, exist_ok=True)
    link = os.path.join(BIN_DIR, "ollama")
    if os.path.isdir(link):  # leftovers from an older, flattened install
        shutil.rmtree(link)
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(binary, link)
    print(f"symlinked   : {link} -> {binary}")
    print(f"\nadd it to your PATH once:  export PATH=\"{BIN_DIR}:$PATH\"")
    print("then:  uv run serve.py --check ; uv run serve.py --pull ; uv run serve.py")


def check_exec(binary):
    """Run the binary. A PermissionError here means the mount forbids exec, not a bad mode."""
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
    except PermissionError as e:
        return False, f"{e} (the filesystem looks like it is mounted noexec)"
    except OSError as e:
        return False, str(e)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


def extract(path, dest):
    """Unpack a .tar.zst. Returns the member names, or None if nothing worked.
    Python < 3.14 cannot read zstd through tarfile, so the CLI and the `zstandard` package
    are real fallbacks - silently returning success here is how a broken install slips through."""
    try:
        with tarfile.open(path) as t:
            names = t.getnames()
            t.extractall(dest)
        return names
    except (tarfile.TarError, ValueError, NotImplementedError, EOFError):
        pass
    if shutil.which("tar"):
        r = subprocess.run(["tar", "--zstd", "-xf", path, "-C", dest], capture_output=True)
        if r.returncode == 0:
            return subprocess.run(["tar", "--zstd", "-tf", path], capture_output=True,
                                  text=True).stdout.split()
    if shutil.which("unzstd") or shutil.which("zstd"):
        exe = shutil.which("unzstd") or shutil.which("zstd")
        args = [exe, "-c", path] if exe.endswith("unzstd") else [exe, "-dc", path]
        plain = path + ".tar"
        with open(plain, "wb") as f:
            if subprocess.run(args, stdout=f, stderr=subprocess.DEVNULL).returncode == 0:
                with tarfile.open(plain) as t:
                    names = t.getnames()
                    t.extractall(dest)
                os.remove(plain)
                return names
        if os.path.exists(plain):
            os.remove(plain)
    try:  # last resort: pip-install the codec into the current venv
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "zstandard"],
                       capture_output=True)
        with tarfile.open(path) as t:
            names = t.getnames()
            t.extractall(dest)
        return names
    except Exception:
        return None


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
    ap.add_argument("--install", action="store_true", help="download the ollama release into ~/ollama")
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
