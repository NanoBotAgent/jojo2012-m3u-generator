#!/usr/bin/env python3
"""Build the JoJo's Bizarre Adventure (2012) release with English subtitles.

The source is the Anime Time BD repackage (nyaa 1681123). Every episode is a
separate file in the torrent, so each one can be fetched on its own with
aria2c --select-file and turned into a 720p H.264 MP4 with the English
subtitle track burned into the picture.

Subcommands
-----------
plan      List the Season 01 episodes inside the torrent.
matrix    Turn an episode list such as "1-26" into a JSON array.
release   Create the GitHub Release the assets are uploaded to.
episode   Download one episode, transcode it, and upload it.
m3u       Write the M3U that points at the uploaded assets.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from episode_titles import display_name
from publish_release import (API, create_release, emit, headers, log, repo_parts,
                             requests_module, upload_asset, write_m3u)

TORRENT_ID = "1681123"
TORRENT_URL = "https://nyaa.si/download/%s.torrent" % TORRENT_ID
ASSET_TEMPLATE = "JoJo_2012_Eng_EP%02d_720p.mp4"
WIDTH = 1280
HEIGHT = 720
VIDEO_CODEC = "libx264"
VIDEO_PRESET = "veryfast"
VIDEO_CRF = "20"
AUDIO_BITRATE = "160k"
TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://open.nyaatorrents.info:6544/announce",
]
DOWNLOAD_TIMEOUT = 2400


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def workdir_root():
    """Pick the volume with the most free space that we can actually write to.

    Some runner images mount /mnt read-only or owned by root, so writability
    is probed rather than assumed.
    """
    candidates = ["/mnt", "/tmp", os.environ.get("WORK_DIR") or "/tmp"]
    writable = []
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".jojo-write-probe")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.remove(probe)
            writable.append((path, shutil.disk_usage(path).free))
        except OSError:
            continue
    if not writable:
        raise SystemExit("::error::No writable work directory")
    writable.sort(key=lambda item: item[1], reverse=True)
    for path, free in writable:
        log("  work root: %s (%.1f GB free)" % (path, free / 1073741824.0))
    return writable[0][0]


def torrent_files(path):
    """Return [(index, path)] using aria2's own numbering.

    The lengths recorded in the torrent metadata do not match the files the
    swarm actually serves, so the metadata is not trusted for anything.
    aria2's --show-files output is the authority, because --select-file is
    resolved against exactly that list.
    """
    out = subprocess.run(["aria2c", "--show-files", path],
                         capture_output=True, text=True, check=True).stdout
    files = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        fields = [f.strip() for f in line.split("|")]
        head = fields[0]
        if not head.isdigit():
            continue
        # The listing has been seen as "IDX|PATH" and as "IDX|PATH|SIZE".
        # The path is the field that carries a file extension.
        path_field = None
        for field in fields[1:]:
            if re.search(r"\.[A-Za-z0-9]{2,4}$", field):
                path_field = field
                break
        if path_field is None:
            path_field = fields[1] if len(fields) > 1 else ""
        files.append((int(head), path_field))
    if not files:
        raise SystemExit("::error::aria2 listed no files for the torrent")
    return files


SEASON_DIR = "Season 01"


def season_one_episodes(files):
    """Pick the Season 01 files and map them onto episode numbers."""
    episodes = {}
    for index, path in files:
        if SEASON_DIR not in path:
            continue
        match = re.search(r" - (\d{2})\.mkv$", path)
        if not match:
            continue
        number = int(match.group(1))
        if not 1 <= number <= 26:
            continue
        if number in episodes:
            raise SystemExit("::error::Two files claim episode %d" % number)
        episodes[number] = {"episode": number, "index": index, "path": path}
    missing = [n for n in range(1, 27) if n not in episodes]
    if missing:
        raise SystemExit("::error::Torrent is missing episodes: %s" % missing)
    return [episodes[n] for n in range(1, 27)]


def fetch_torrent(dest):
    """Download the .torrent file and return its path."""
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    log("  fetching torrent metadata")
    run(["curl", "-sSL", "--max-time", "120", "-A", "Mozilla/5.0",
         TORRENT_URL, "-o", dest])
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        raise SystemExit("::error::Could not download the torrent metadata")
    return dest


def build_plan(dest=None):
    """Return the Season 01 episode plan, downloading the torrent if needed."""
    if dest is None:
        dest = os.path.join(workdir_root(), "jojo-plan", "source.torrent")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fetch_torrent(dest)
    return season_one_episodes(torrent_files(dest))


def cmd_plan(args):
    episodes = build_plan()
    log("  season 01 episodes: %d" % len(episodes))
    for ep in episodes:
        log("    ep %2d  idx %3d  %s"
            % (ep["episode"], ep["index"], ep["path"].split("/")[-1]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"torrent_id": TORRENT_ID, "episodes": episodes}, fh, indent=2)
        log("  wrote %s" % args.out)
    return 0


def parse_episodes(spec):
    """Turn "1-26" or "1,4,9" into a list of episode numbers."""
    numbers = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            low, high = chunk.split("-", 1)
            numbers.extend(range(int(low), int(high) + 1))
        else:
            numbers.append(int(chunk))
    numbers = [n for n in numbers if 1 <= n <= 26]
    if not numbers:
        raise SystemExit("::error::No episodes selected")
    return sorted(set(numbers))


def cmd_matrix(args):
    numbers = parse_episodes(args.episodes)
    emit("episodes", json.dumps(numbers))
    full = numbers == list(range(1, 27))
    emit("full_set", "true" if full else "false")
    log("  matrix: %s (full set: %s)" % (json.dumps(numbers), full))
    return 0


def cmd_release(args):
    owner, repo = repo_parts()
    if not args.tag:
        raise SystemExit("::error::A release tag is required")
    body = "\n".join([
        "JoJo's Bizarre Adventure (2012) - 720p, English subtitles",
        "",
        "Episodes 1-9: Phantom Blood",
        "Episodes 10-26: Battle Tendency",
        "",
        "Source: Anime Time BD repackage (1080p HEVC, dual audio, English soft subs)",
        "The English subtitle track is burned into the picture.",
        "",
        "Generated on run %s" % os.environ.get("GITHUB_RUN_NUMBER", "0"),
    ])
    rel = create_release(owner, repo, args.tag, "JoJo 2012 720p English Subs (Episodes 1-26)", body)
    log("  tag: %s  id: %s" % (args.tag, rel["id"]))
    emit("release_id", str(rel["id"]))
    emit("release_tag", args.tag)
    emit("release_url", rel["html_url"])
    return 0


def download_episode(torrent, index, outdir, episode):
    """Pull one file out of the torrent with aria2 and return its path.

    The length recorded in the torrent metadata does not match the file the
    swarm actually serves, so the downloaded file is identified by its path
    and checked with ffprobe rather than by comparing sizes.
    """
    os.makedirs(outdir, exist_ok=True)
    cmd = [
        "aria2c", "--dir=" + outdir, "--select-file=%d" % index,
        "--allow-overwrite=true", "--auto-file-renaming=false",
        "--file-allocation=none", "--bt-enable-lpd=true",
        "--follow-torrent=mem", "--seed-time=0",
        "--connect-timeout=30", "--timeout=60", "--summary-interval=20",
        "--console-log-level=warn",
    ]
    for tracker in TRACKERS:
        cmd.append("--bt-tracker=" + tracker)
    cmd.append(torrent)

    log("  downloading episode %d (aria2 select-file %d)" % (episode, index))
    started = time.time()
    try:
        run(cmd, timeout=DOWNLOAD_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SystemExit("::error::Download timed out after %d s" % DOWNLOAD_TIMEOUT)
    except subprocess.CalledProcessError as exc:
        log("  ::warning::aria2 exited %d" % exc.returncode)

    found = []
    for base, _dirs, names in os.walk(outdir):
        for name in names:
            if name.endswith(".mkv"):
                found.append(os.path.join(base, name))
    if not found:
        raise SystemExit("::error::No episode file landed on disk")
    pattern = re.compile(r" - %02d\.mkv$" % episode)
    named = [p for p in found
             if pattern.search(os.path.basename(p)) and SEASON_DIR in p]
    if len(named) != 1:
        raise SystemExit("::error::Expected exactly one episode %d file, found %d: %s"
                         % (episode, len(named), named))
    path = named[0]
    size = os.path.getsize(path)
    elapsed = max(time.time() - started, 1)
    log("  downloaded %.1f MB in %.0f s (%.1f MB/s)"
        % (size / 1048576.0, elapsed, size / 1048576.0 / elapsed))
    log("  file: %s" % path.replace(outdir, "").lstrip("/"))
    return path


def extract_subtitle(source, dest, track):
    """Pull the English ASS track out of the source file."""
    run(["ffmpeg", "-v", "error", "-y", "-i", source,
         "-map", "0:%d" % track, "-c:s", "ass", dest])
    if not os.path.exists(dest) or os.path.getsize(dest) < 500:
        raise SystemExit("::error::Subtitle extraction produced nothing")
    log("  subtitle track %d extracted (%d bytes)" % (track, os.path.getsize(dest)))
    return dest


def transcode(source, subtitle, dest, cwd):
    """Downscale to 720p, burn the English subs in, and encode H.264.

    The filter order matters. The video is scaled and converted to 8-bit
    before the subtitles filter runs, because libass renders text into the
    frame it is given and 10-bit input is an unnecessary complication. The
    ASS file carries its own PlayResX and PlayResY, so libass scales the
    text down to the new frame size on its own.

    The subtitle file is referred to by bare name and ffmpeg runs from the
    directory that holds it. A full path would need escaping for the filter
    syntax, and the work path can contain characters that break it.
    """
    vf = "scale=%d:%d,format=yuv420p,subtitles=%s" % (WIDTH, HEIGHT, subtitle)
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", source,
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a:1",
        "-c:v", VIDEO_CODEC, "-preset", VIDEO_PRESET, "-crf", VIDEO_CRF,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-ac", "2", "-movflags", "+faststart",
        dest,
    ]
    log("  transcoding to 720p H.264 with burned-in English subs")
    started = time.time()
    run(cmd, cwd=cwd)
    elapsed = max(time.time() - started, 1)
    size = os.path.getsize(dest)
    log("  encoded %.1f MB in %.0f s" % (size / 1048576.0, elapsed))
    return dest


def verify_output(path):
    """Confirm the result is 720p video with audio and no leftover sub track."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,width,height:stream_tags=language,title",
         "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    streams = json.loads(out).get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    if not video or video[0].get("width") != WIDTH or video[0].get("height") != HEIGHT:
        raise SystemExit("::error::Output is not %dx%d" % (WIDTH, HEIGHT))
    if not audio:
        raise SystemExit("::error::Output has no audio track")
    if subs:
        raise SystemExit("::error::Output still carries %d subtitle tracks" % len(subs))
    duration = float(json.loads(out).get("format", {}).get("duration", 0))
    log("  verified: %s %dx%d, %d audio track(s), no subtitle track, %.0f s long"
        % (video[0].get("codec_name"), WIDTH, HEIGHT, len(audio), duration))
    if duration < 1000 or duration > 1800:
        raise SystemExit("::error::Unexpected duration %.0f s" % duration)


def capture_frames(video, outdir, stamps=(120, 420, 1200)):
    """Grab a few frames so a human can confirm the subtitles look right."""
    os.makedirs(outdir, exist_ok=True)
    saved = []
    for stamp in stamps:
        target = os.path.join(outdir, "frame_%04d.png" % stamp)
        try:
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(stamp), "-i", video,
                 "-frames:v", "1", target])
        except subprocess.CalledProcessError:
            continue
        if os.path.exists(target) and os.path.getsize(target) > 1000:
            saved.append(target)
    if saved:
        log("  captured %d frame(s) for visual check" % len(saved))
    return saved


def cmd_episode(args):
    episodes = build_plan()
    match = [ep for ep in episodes if ep["episode"] == args.episode]
    if not match:
        raise SystemExit("::error::Episode %d is not in the torrent" % args.episode)
    ep = match[0]

    owner, repo = repo_parts()
    root = workdir_root()
    workdir = os.path.join(root, "jojo-ep%02d" % args.episode)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    try:
        torrent = os.path.join(workdir, "source.torrent")
        fetch_torrent(torrent)
        source = download_episode(torrent, ep["index"], os.path.join(workdir, "src"),
                                  args.episode)
        extract_subtitle(source, os.path.join(workdir, "subs.ass"), args.subtitle_track)
        output = transcode(source, "subs.ass", os.path.join(workdir, "out.mp4"), workdir)
        verify_output(output)
        frame_dir = os.environ.get("JOJO_FRAME_DIR") or os.path.join(workdir, "frames")
        capture_frames(output, frame_dir)

        name = ASSET_TEMPLATE % args.episode
        log("  uploading %s" % name)
        upload_asset(owner, repo, args.release_id, name, output)
        log("  uploaded")
        emit("uploaded_asset", name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


def release_asset_names(owner, repo, tag):
    """Return the set of asset names attached to a release."""
    requests = requests_module()
    resp = requests.get(f"{API}/repos/{owner}/{repo}/releases/tags/{tag}",
                        headers=headers(), timeout=60)
    if resp.status_code != 200:
        raise SystemExit("::error::Could not read release %s (%d)" % (tag, resp.status_code))
    return {a.get("name") for a in resp.json().get("assets", [])}


def cmd_m3u(args):
    owner, repo = repo_parts()
    episodes = [{"index": n, "filename": ASSET_TEMPLATE % n} for n in range(1, 27)]

    # Never repoint the M3U at a release that is missing episodes. The M3U in
    # the repo is the working deliverable, so a partial build must not touch it.
    present = release_asset_names(owner, repo, args.tag)
    wanted = [ep["filename"] for ep in episodes]
    missing = [name for name in wanted if name not in present]
    if missing:
        raise SystemExit("::error::Release %s is missing %d asset(s): %s"
                         % (args.tag, len(missing), ", ".join(missing[:6])))
    log("  release holds all %d episode assets" % len(wanted))

    base_url = "https://github.com/%s/%s/releases/download/%s" % (owner, repo, args.tag)
    write_m3u(args.out, episodes, base_url)
    log("  first entry: %s" % display_name(1))
    emit("m3u_file", os.path.abspath(args.out))
    emit("episode_count", str(len(episodes)))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--out")
    plan.set_defaults(func=cmd_plan)

    matrix = sub.add_parser("matrix")
    matrix.add_argument("--episodes", default="1-26")
    matrix.set_defaults(func=cmd_matrix)

    release = sub.add_parser("release")
    release.add_argument("--tag", required=True)
    release.set_defaults(func=cmd_release)

    episode = sub.add_parser("episode")
    episode.add_argument("--episode", type=int, required=True)
    episode.add_argument("--release-id", required=True)
    episode.add_argument("--subtitle-track", type=int, default=int(os.environ.get("SUBTITLE_TRACK", "3")))
    episode.set_defaults(func=cmd_episode)

    m3u = sub.add_parser("m3u")
    m3u.add_argument("--tag", required=True)
    m3u.add_argument("--out", default="jojo2012-720p.m3u")
    m3u.set_defaults(func=cmd_m3u)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
