"""Upload a built file (e.g. eboot.bin) or update longshot_env.txt on a PS5 via FTP."""
import argparse
import ftplib
import io
import os
import sys
import time


def list_names(ftp):
    lines = []
    ftp.retrlines("LIST", lines.append)
    return {line.split()[-1] for line in lines if line.split()}


def safe_delete(ftp, name):
    try:
        ftp.delete(name)
    except ftplib.error_reply as e:
        # ftpsrv.elf returns 226 File deleted instead of 250
        if not str(e).startswith("226"):
            raise


def update_env(ftp, set_vars, unset_keys):
    buf = io.BytesIO()
    try:
        ftp.retrbinary("RETR longshot_env.txt", buf.write)
        lines = buf.getvalue().decode("utf-8", errors="replace").splitlines()
    except ftplib.error_perm:
        lines = []

    kv = {}
    for item in set_vars:
        if "=" not in item:
            sys.exit(f"ERROR: --set-env expects KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        kv[k] = v

    unset = set(unset_keys)
    out = []
    seen = set()
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0]
            if k in unset:
                continue
            if k in kv:
                out.append(f"{k}={kv[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in kv.items():
        if k not in seen:
            out.append(f"{k}={v}")

    ftp.storbinary("STOR longshot_env.txt", io.BytesIO(("\n".join(out) + "\n").encode("utf-8")))
    print("Updated longshot_env.txt on PS5.")


def main():
    parser = argparse.ArgumentParser(description="Upload Longshot files to a PS5 via FTP.")
    parser.add_argument(
        "--host",
        default=os.environ.get("PS5_FTP_HOST"),
        required=os.environ.get("PS5_FTP_HOST") is None,
        help="PS5 IP address (or set PS5_FTP_HOST)",
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("PS5_FTP_PORT", "2121")), help="FTP port (default: 2121)")
    parser.add_argument("--remote-dir", default="/data/homebrew/PPSA99198", help="Target directory on PS5")
    parser.add_argument("--file", default=None, help="Local file to upload")
    parser.add_argument("--remote-name", default=None, help="Remote filename (default: basename of --file)")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak backup before replacing")
    parser.add_argument("--set-env", action="append", default=[], help="Set KEY=VALUE in remote longshot_env.txt")
    parser.add_argument("--unset-env", action="append", default=[], help="Remove KEY from remote longshot_env.txt")
    args = parser.parse_args()

    if not args.file and not args.set_env and not args.unset_env:
        parser.error("Provide --file, --set-env, or --unset-env.")

    ftp = ftplib.FTP()
    print(f"Connecting to {args.host}:{args.port} ...")
    ftp.connect(args.host, args.port, timeout=15)
    ftp.login()
    ftp.cwd(args.remote_dir)

    if args.file:
        if not os.path.isfile(args.file):
            sys.exit(f"ERROR: Local file not found: {args.file}")
        remote_name = args.remote_name or os.path.basename(args.file)
        total_size = os.path.getsize(args.file)
        existing = list_names(ftp)

        bak_name = remote_name + ".bak"
        if not args.no_backup and remote_name in existing and bak_name not in existing:
            print(f"Backing up {remote_name} -> {bak_name} ...")
            ftp.rename(remote_name, bak_name)
        elif remote_name in existing:
            print(f"Deleting existing {remote_name} before upload ...")
            safe_delete(ftp, remote_name)

        uploaded = 0
        last_print = time.time()
        start_time = time.time()

        def callback(data):
            nonlocal uploaded, last_print
            uploaded += len(data)
            now = time.time()
            if now - last_print >= 2.0 or uploaded == total_size:
                last_print = now
                elapsed = now - start_time
                speed = (uploaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                pct = (uploaded / total_size) * 100 if total_size else 100
                print(f"Progress: {uploaded / (1024 * 1024):.1f}/{total_size / (1024 * 1024):.1f} MB ({pct:.1f}%) @ {speed:.2f} MB/s")

        print(f"Uploading {args.file} -> {args.remote_dir}/{remote_name} ...")
        with open(args.file, "rb") as f:
            ftp.storbinary(f"STOR {remote_name}", f, blocksize=4 * 1024 * 1024, callback=callback)

        remote_size = ftp.size(remote_name)
        print(f"Upload finished. Remote size: {remote_size} bytes (local: {total_size} bytes)")
        if remote_size != total_size and remote_name == "eboot.bin":
            print("Note: PS5 ftpsrv/etaHEN may unpack SELF -> ELF on disk, changing byte size.")

    if args.set_env or args.unset_env:
        update_env(ftp, args.set_env, args.unset_env)

    ftp.quit()
    print("Done!")


if __name__ == "__main__":
    main()
