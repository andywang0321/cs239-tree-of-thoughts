"""Start Ollama without root, keep it running, pull the models, verify the GPU is in use.

    uv run serve.py --check        # report what is installed, running, and on which device
    uv run serve.py --pull         # download the two 2023 models into ~/ollama-models
    uv run serve.py                # start the server in the foreground (Ctrl-C to stop)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import llm  # noqa: F401  - imports the resolved OLLAMA_BIN path
from llm import OLLAMA_BIN

HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
MODELS_DIR = os.environ.get("OLLAMA_MODELS", os.path.expanduser("~/ollama-models"))
TAGS = ["llama2:7b-chat", "mistral:7b-instruct"]


def api(path):
    with urllib.request.urlopen(f"http://{HOST}{path}", timeout=5) as r:
        return json.load(r)


def installed():
    """Report the binary, the model store, and whether a server is already answering."""
    print(f"binary      : {OLLAMA_BIN}")
    found = shutil.which(OLLAMA_BIN) or (OLLAMA_BIN if os.path.exists(OLLAMA_BIN) else None)
    if found:
        v = subprocess.run([found, "--version"], capture_output=True, text=True).stdout.strip()
        print(f"version     : {v or 'unknown'}")
    else:
        print("version     : NOT FOUND - download the binary (see --help)")
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
        print("server      : not running")


def start():
    found = shutil.which(OLLAMA_BIN) or (OLLAMA_BIN if os.path.exists(OLLAMA_BIN) else None)
    if not found:
        sys.exit(f"ollama binary not found (looked for {OLLAMA_BIN}). "
                 "Set OLLAMA_BIN=/path/to/ollama or see the README.")
    os.makedirs(MODELS_DIR, exist_ok=True)
    env = {**os.environ, "OLLAMA_HOST": HOST, "OLLAMA_MODELS": MODELS_DIR}
    print(f"starting {found} on {HOST}, models in {MODELS_DIR}")
    print("keep this terminal open (or run it under tmux/nohup); Ctrl-C to stop")
    subprocess.run([found, "serve"], env=env)


def pull():
    found = shutil.which(OLLAMA_BIN) or OLLAMA_BIN
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
    ap.add_argument("--pull", action="store_true", help="download both models")
    ap.add_argument("--gpu", action="store_true", help="verify GPU offload")
    a = ap.parse_args()
    if a.check:
        installed()
    elif a.pull:
        pull()
    elif a.gpu:
        gpu_check()
    else:
        start()


if __name__ == "__main__":
    main()
