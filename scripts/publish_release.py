#!/usr/bin/env python3
"""
Publish a JoJo 2012 release: create the GitHub Release, upload every episode
as an asset, and write the M3U that points at those assets.

Disk strategy
-------------
The source archive is 6.7 GB. The old workflow unzipped everything AND copied
it to a second directory, needing ~18.6 GB and dying on the runner.

Now the archive is downloaded once and the episodes are extracted one at a
time: extract -> upload -> delete. Peak disk is the archive plus a single
episode (~7 GB), and the archive itself is removed at the end.

If disk is too tight, set STREAM_FROM_REMOTE=1 to read members straight out of
the remote archive over HTTP range requests instead. That uses only one
episode of disk at a time, but is much slower.
"""
import os
import shutil
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from episode_titles import display_name

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
CHUNK = 1 << 20
UA = "Mozilla/5.0"

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".mpg", ".mpeg", ".wmv", ".flv", ".webm"}

# PixelDrain batch archives, one per resolution.
ZIP_URLS = {
    "360p": "https://pixeldrain.com/api/file/ApBTtMCs",
    "480p": "https://pixeldrain.com/api/file/qmkbjjRz",
    "720p": "https://pixeldrain.com/api/file/b5gcL8LM",
}


def log(msg):
    print(msg, flush=True)


def requests_module():
    """Imported lazily so the module can be inspected without the dependency."""
    import requests

    return requests


def emit(key, value):
    """Write a step output. Only key=value lines go to GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")
    print(f"{key}={value}")


def repo_parts():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise SystemExit("::error::GITHUB_REPOSITORY is not set")
    owner, name = repo.split("/", 1)
    return owner, name


def headers():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("::error::GITHUB_TOKEN is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def episode_index(filename):
    """Pull the episode index out of a name like Alqanime_Jojo_BD_07_720p.mp4."""
    import re

    base = os.path.basename(filename)
    match = re.search(r"_(\d{2})(?:_END)?_", base)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{2})", base)
    if match:
        return int(match.group(1))
    return None


def pick_workdir():
    """Pick a work directory on the volume with the most free space.

    GitHub runners expose several filesystems and the root one is small.
    The 6.7 GB archive has to live somewhere with room, so measure instead
    of assuming. Free space alone is not enough: a directory can be
    readable and still not writable, so create a file to prove it.
    """
    candidates = []
    env_dir = os.environ.get("WORK_DIR")
    if env_dir:
        candidates.append(env_dir)
    candidates += ["/mnt", "/tmp", tempfile.gettempdir()]

    best = None
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            usage = shutil.disk_usage(path)
            probe = os.path.join(path, ".jojo-write-probe")
            with open(probe, "wb") as fh:
                fh.write(b"0")
            os.remove(probe)
        except OSError as exc:
            log("  candidate %-28s not writable (%s)" % (path, exc))
            continue
        log("  candidate %-28s %8.1f GB free, writable" % (path, usage.free / 1073741824.0))
        if best is None or usage.free > best[1]:
            best = (path, usage.free)
    if best is None:
        raise SystemExit("::error::No writable work directory found")
    log("  work dir: %s (%.1f GB free)" % (best[0], best[1] / 1073741824.0))
    workdir = tempfile.mkdtemp(prefix="jojo-", dir=best[0])
    log("  created %s" % workdir)
    return workdir


def download_archive(url, dest, attempt=1):
    """Download the archive to dest, resuming a partial file if one exists.

    A dropped connection mid-transfer is common with a 6.7 GB pull, so a
    failure retries with a Range request instead of starting over.
    """
    requests = requests_module()
    total = 0
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"
        log(f"  resuming from {have / 1048576.0:.0f} MB")
    started = time.time()
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(60, 600)) as resp:
            if resp.status_code not in (200, 206):
                raise SystemExit(f"::error::Archive download failed ({resp.status_code})")
            if resp.status_code == 200 and have:
                have = 0
            mode = "ab" if (resp.status_code == 206 and have) else "wb"
            with open(dest, mode) as fh:
                for block in resp.iter_content(CHUNK):
                    if not block:
                        continue
                    fh.write(block)
                    total += len(block)
                    if total % (256 * 1048576) < CHUNK:
                        log("    ... %.1f GB" % ((have + total) / 1073741824.0))
    except SystemExit:
        raise
    except Exception as exc:
        if attempt < 5:
            wait = 20 * attempt
            log(f"  ::warning::Download interrupted ({exc}); retry {attempt} in {wait}s")
            time.sleep(wait)
            return download_archive(url, dest, attempt + 1)
        raise SystemExit(f"::error::Archive download failed after {attempt} attempts: {exc}")
    elapsed = time.time() - started
    size = os.path.getsize(dest)
    log("  archive       : %.2f GB in %.0f s (%.1f MB/s)"
        % (size / 1073741824.0, elapsed, size / 1048576.0 / max(elapsed, 1)))
    return dest


def episodes_from_infos(videos):
    """Turn archive members into an ordered, de-duplicated episode list."""
    episodes = []
    for info in videos:
        index = episode_index(info.filename)
        if index is None:
            log("  ::warning::No episode number in %s, skipping" % info.filename)
            continue
        episodes.append({
            "index": index,
            "member": info.filename,
            "filename": os.path.basename(info.filename),
            "size": info.file_size,
        })
    episodes.sort(key=lambda e: e["index"])
    seen = set()
    deduped = []
    for ep in episodes:
        if ep["index"] in seen:
            log("  ::warning::Duplicate episode %d, keeping first" % ep["index"])
            continue
        seen.add(ep["index"])
        deduped.append(ep)
    return deduped


def list_episodes_from_zip(path):
    with zipfile.ZipFile(path, "r") as zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        videos = [i for i in members
                  if os.path.splitext(i.filename)[1].lower() in VIDEO_EXTS]
    return episodes_from_infos(videos), len(members)


def list_episodes_from_remote(url):
    from http_zip import open_remote_zip

    zf, hf = open_remote_zip(url)
    try:
        members = [i for i in zf.infolist() if not i.is_dir()]
        videos = [i for i in members
                  if os.path.splitext(i.filename)[1].lower() in VIDEO_EXTS]
    finally:
        zf.close()
    log("  remote size   : %.2f GB" % (hf.size / 1073741824.0))
    return episodes_from_infos(videos), len(members), hf.size


def create_release(owner, repo, tag, name, body):
    requests = requests_module()
    resp = requests.post(
        f"{API}/repos/{owner}/{repo}/releases",
        headers={**headers(), "Content-Type": "application/json"},
        json={"tag_name": tag, "name": name, "body": body,
              "draft": False, "prerelease": False},
        timeout=60,
    )
    if resp.status_code == 422:
        # Tag already exists from a previous run: reuse that release.
        existing = requests.get(f"{API}/repos/{owner}/{repo}/releases/tags/{tag}",
                                headers=headers(), timeout=60)
        if existing.status_code == 200:
            log("  release already exists, reusing it")
            return existing.json()
        raise SystemExit(f"::error::Could not create release: {resp.text[:400]}")
    if resp.status_code not in (200, 201):
        raise SystemExit(f"::error::Create release failed ({resp.status_code}): {resp.text[:400]}")
    return resp.json()


def upload_asset(owner, repo, release_id, filename, path, attempt=1):
    requests = requests_module()
    url = f"{UPLOADS}/repos/{owner}/{repo}/releases/{release_id}/assets?name={filename}"
    size = os.path.getsize(path)
    upload_headers = {
        **headers(),
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size),
    }
    with open(path, "rb") as fh:
        resp = requests.post(url, headers=upload_headers, data=fh, timeout=(60, 3600))
    if resp.status_code == 201:
        return 201
    if resp.status_code == 422:
        # Already uploaded by an earlier attempt. If the stored asset is the
        # same size, keep it. If it is a different size, the earlier upload
        # was truncated, so replace it rather than fail forever.
        listing = requests.get(
            f"{API}/repos/{owner}/{repo}/releases/{release_id}/assets",
            headers=headers(), timeout=60)
        if listing.status_code == 200:
            for asset in listing.json():
                if asset.get("name") != filename:
                    continue
                if asset.get("size") == size:
                    log("    asset already present with matching size, keeping it")
                    return 422
                log("    asset exists with size %s, expected %s, replacing"
                    % (asset.get("size"), size))
                requests.delete(f"{API}/repos/{owner}/{repo}/releases/assets/{asset['id']}",
                                headers=headers(), timeout=60)
                time.sleep(2)
                return upload_asset(owner, repo, release_id, filename, path, attempt)
        raise SystemExit(f"::error::Upload of {filename} rejected: {resp.text[:300]}")
    if resp.status_code >= 500 and attempt < 4:
        wait = 15 * attempt
        log(f"    retry {attempt} in {wait}s (HTTP {resp.status_code})")
        time.sleep(wait)
        return upload_asset(owner, repo, release_id, filename, path, attempt + 1)
    raise SystemExit(f"::error::Upload of {filename} failed ({resp.status_code}): {resp.text[:300]}")


def extract_from_zip(path, member, dest, expected):
    with zipfile.ZipFile(path, "r") as zf:
        info = zf.getinfo(member)
        written = 0
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                out.write(block)
                written += len(block)
    if expected and written != expected:
        raise SystemExit(f"::error::Size mismatch for {member}: {written} != {expected}")
    return written


def extract_from_remote(url, member, dest, expected):
    from http_zip import open_remote_zip

    zf, _ = open_remote_zip(url)
    try:
        info = zf.getinfo(member)
        written = 0
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                out.write(block)
                written += len(block)
    finally:
        zf.close()
    if expected and written != expected:
        raise SystemExit(f"::error::Size mismatch for {member}: {written} != {expected}")
    return written


def write_m3u(path, episodes, base_url):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#EXTM3U\n")
        for ep in episodes:
            index = ep["index"]
            name = display_name(index) if 1 <= index <= 26 else f"Episode {index:02d}"
            fh.write(f'#EXTINF:-1 tvg-id="jojo2012-{index:02d}" tvg-name="{name}",{name}\n')
            fh.write(f"{base_url}/{ep['filename']}\n")
    log(f"  wrote {path} with {len(episodes)} entries")


def report_episodes(episodes, member_count):
    log("  members       : %d" % member_count)
    log("  episodes      : %d" % len(episodes))
    for ep in episodes:
        log("    ep %2d  %-52s %8.1f MB"
            % (ep["index"], ep["filename"], ep["size"] / 1048576.0))


def main():
    resolution = os.environ.get("JOJO_RESOLUTION", "720p")
    url = os.environ.get("ZIP_URL", "") or ZIP_URLS.get(resolution, "")
    limit = int(os.environ.get("MAX_EPISODES", "26") or 0)
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "0")
    m3u_file = os.environ.get("M3U_FILE") or f"jojo2012-{resolution}.m3u"
    create = os.environ.get("CREATE_RELEASE", "true").lower() == "true"
    stream_remote = os.environ.get("STREAM_FROM_REMOTE", "false").lower() == "true"

    if not url:
        raise SystemExit("::error::No archive URL for resolution %r" % resolution)
    log("  archive url   : %s" % url)

    owner, repo = repo_parts()
    tag = f"jojo2012-{resolution}-{run_number}"
    base_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}"

    # Listing only: read the remote central directory instead of pulling
    # 6.7 GB just to count files.
    if not create:
        log("=== episodes ===")
        episodes, member_count, _ = list_episodes_from_remote(url)
        report_episodes(episodes, member_count)
        if limit and len(episodes) < limit:
            raise SystemExit(f"::error::Expected {limit} episodes, found {len(episodes)}")
        log("")
        log("=== no release requested, listing only ===")
        emit("episode_count", str(len(episodes)))
        emit("release_tag", tag)
        return 0

    workdir = pick_workdir()
    archive = os.path.join(workdir, "source.zip")
    try:
        log("=== episodes ===")
        if stream_remote:
            episodes, member_count, _ = list_episodes_from_remote(url)
            extract = lambda m, d, e: extract_from_remote(url, m, d, e)
        else:
            log("  downloading archive ...")
            download_archive(url, archive)
            episodes, member_count = list_episodes_from_zip(archive)
            extract = lambda m, d, e: extract_from_zip(archive, m, d, e)
        report_episodes(episodes, member_count)
        if limit and len(episodes) < limit:
            raise SystemExit(f"::error::Expected {limit} episodes, found {len(episodes)}")

        log("")
        log("=== release ===")
        body = "\n".join([
            f"JoJo's Bizarre Adventure 2012 - {resolution}",
            "",
            "Episodes 1-9: Phantom Blood",
            "Episodes 10-26: Battle Tendency",
            "",
            "Source: Alqanime (BD, Indonesian hard-subs)",
            "Downloaded from PixelDrain batch ZIP",
            "",
            f"Generated on run {run_number}",
        ])
        rel = create_release(owner, repo, tag, f"JoJo 2012 {resolution} (Episodes 1-26)", body)
        release_id = rel["id"]
        log("  tag    : %s" % tag)
        log("  id     : %s" % release_id)
        log("  url    : %s" % rel["html_url"])

        log("")
        log("=== upload ===")
        for ep in episodes:
            target = os.path.join(workdir, ep["filename"])
            log(f"  [{ep['index']:02d}/{len(episodes):02d}] {ep['filename']} "
                f"({ep['size'] / 1048576.0:.1f} MB)")
            extract(ep["member"], target, ep["size"])
            upload_asset(owner, repo, release_id, ep["filename"], target)
            os.remove(target)
            log("         uploaded, local copy removed")

        log("")
        log("=== m3u ===")
        write_m3u(m3u_file, episodes, base_url)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    emit("release_tag", tag)
    emit("m3u_file", m3u_file)
    emit("episode_count", str(len(episodes)))
    emit("release_url", f"https://github.com/{owner}/{repo}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
