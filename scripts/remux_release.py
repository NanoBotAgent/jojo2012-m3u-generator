#!/usr/bin/env python3
"""Build the JoJo's Bizarre Adventure (2012) 1080p release with soft English subs.

This uses the same source as the 720p build (the Anime Time BD repackage: 1080p
HEVC 10-bit, dual audio, an English ASS subtitle track), but nothing is
encoded here. The video and both audio tracks are stream copied and the
English subtitle track is muxed into the MP4 as a soft mov_text track, so the
picture keeps the source quality and an episode takes about a minute instead
of the twelve the 720p transcode costs.

Subcommands
-----------
plan      List the Season 01 episodes inside the torrent.
matrix    Turn an episode list such as "1-26" into a JSON array.
release   Create the GitHub Release the assets are uploaded to.
episode   Download one episode, remux it, and upload it.
m3u       Write the M3U that points at the uploaded assets.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from publish_release import (create_release, emit, log, repo_parts, upload_asset,
                             write_m3u)
from torrent_release import (build_plan, download_episode, extract_subtitle,
                             fetch_torrent, parse_episodes, release_asset_names, run,
                             workdir_root)

ASSET_TEMPLATE = "JoJo_2012_Eng_EP%02d_1080p.mp4"
EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
TEXT_SUBTITLE_CODECS = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text"}


def probe(path):
    """Return the ffprobe description of a media file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,duration,width,height:stream_tags=language,title",
         "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video_duration(data):
    """Length of the video track, falling back to the container length.

    The container length of these MKVs runs about ten seconds past the video
    track itself, so the track is what the remux has to match.
    """
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        try:
            value = float(stream.get("duration"))
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return float(data.get("format", {}).get("duration", 0) or 0)


def stream_label(stream):
    tags = stream.get("tags") or {}
    language = (tags.get("language") or "?").lower()
    title = tags.get("title") or ""
    return "%s%s" % (language, " / " + title if title else "")


def pick_subtitle(source, preferred):
    """Choose the subtitle stream to carry over as a soft track.

    The absolute stream index is honoured while it still points at a text
    track, the same way the 720p build addresses it. Otherwise the first
    English text track is used, and if the source has no English track the
    build stops instead of shipping subtitles in the wrong language.
    """
    data = probe(source)
    subs = [s for s in data.get("streams", []) if s.get("codec_type") == "subtitle"]
    if not subs:
        raise SystemExit("::error::The source carries no subtitle track")
    chosen = {s.get("index"): s for s in subs}.get(preferred)
    if chosen is not None and chosen.get("codec_name") in TEXT_SUBTITLE_CODECS:
        log("  subtitle stream %d selected (%s, %s)"
            % (chosen.get("index"), chosen.get("codec_name"), stream_label(chosen)))
        return chosen
    english = [s for s in subs
               if s.get("codec_name") in TEXT_SUBTITLE_CODECS
               and ("eng" in ((s.get("tags") or {}).get("language") or "").lower()
                    or "english" in ((s.get("tags") or {}).get("title") or "").lower())]
    if not english:
        raise SystemExit("::error::The source has no English text subtitle track")
    chosen = english[0]
    log("  subtitle stream %d selected (%s, %s)"
        % (chosen.get("index"), chosen.get("codec_name"), stream_label(chosen)))
    return chosen


def english_report(path):
    """Count Latin and CJK characters in the dialogue of a subtitle file."""
    latin = 0
    cjk = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("["):
                continue
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                line = parts[9] if len(parts) > 9 else ""
            for char in line:
                if "a" <= char <= "z" or "A" <= char <= "Z":
                    latin += 1
                elif "\u3000" <= char <= "\u9fff" or "\uff00" <= char <= "\uffef":
                    cjk += 1
    return latin, cjk


def require_english(path, what):
    """Fail loudly if the subtitle track is not English dialogue."""
    latin, cjk = english_report(path)
    if latin < 200:
        raise SystemExit("::error::%s has almost no Latin text (%d letters)" % (what, latin))
    if cjk > latin:
        raise SystemExit("::error::%s is not English (%d CJK vs %d Latin)"
                         % (what, cjk, latin))
    log("  %s: %d Latin letters, %d CJK characters" % (what, latin, cjk))


def remux(source, dest, subtitle_index):
    """Copy the video and audio through and mux the subtitle in as a soft track."""
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", source,
        "-map", "0:v:0", "-map", "0:a",
        "-map", "0:%d" % subtitle_index,
        "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:0", "title=English",
        "-movflags", "+faststart",
        dest,
    ]
    log("  remuxing to 1080p HEVC with a soft English subtitle track")
    started = time.time()
    run(cmd)
    elapsed = max(time.time() - started, 1)
    size = os.path.getsize(dest)
    log("  remuxed %.1f MB in %.0f s" % (size / 1048576.0, elapsed))
    return dest


def verify_output(path, source_duration):
    """Confirm the result is 1080p video with audio and one soft subtitle track.

    The length is compared with the source video track. The source runs about
    ten seconds past the last frame it actually holds, so a small shortfall is
    expected and matches what the 720p transcode produces.
    """
    data = probe(path)
    streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    if not video:
        raise SystemExit("::error::Output has no video stream")
    if video[0].get("width") != EXPECTED_WIDTH or video[0].get("height") != EXPECTED_HEIGHT:
        raise SystemExit("::error::Output is not %dx%d"
                         % (EXPECTED_WIDTH, EXPECTED_HEIGHT))
    if not audio:
        raise SystemExit("::error::Output has no audio track")
    if len(subs) != 1:
        raise SystemExit("::error::Output carries %d subtitle tracks, expected 1" % len(subs))
    if subs[0].get("codec_name") != "mov_text":
        raise SystemExit("::error::Subtitle track is %s, not mov_text"
                         % subs[0].get("codec_name"))
    duration = float(data.get("format", {}).get("duration", 0))
    if duration < 1000 or duration > 1800:
        raise SystemExit("::error::Unexpected duration %.0f s" % duration)
    if source_duration and video_duration(data) < source_duration - 15:
        raise SystemExit("::error::Output is %.0f s shorter than the source"
                         % (source_duration - video_duration(data)))
    log("  verified: %s %dx%d, %d audio track(s), %s subtitle track, %.0f s long (source track %.0f s)"
        % (video[0].get("codec_name"), EXPECTED_WIDTH, EXPECTED_HEIGHT, len(audio),
           subs[0].get("codec_name"), duration, source_duration))


def extract_soft_subtitle(video, dest):
    """Pull the muxed soft subtitle back out so it can be checked."""
    run(["ffmpeg", "-v", "error", "-y", "-i", video, "-map", "0:s:0", "-c:s", "srt", dest])
    if not os.path.exists(dest) or os.path.getsize(dest) < 200:
        raise SystemExit("::error::The soft subtitle track came back empty")
    return dest


def capture_frames(video, subtitle, outdir, stamps=(120, 420, 1200)):
    """Grab a few frames with the soft subtitle rendered, for a visual check."""
    os.makedirs(outdir, exist_ok=True)
    cwd = os.path.dirname(os.path.abspath(subtitle))
    name = os.path.basename(subtitle)
    saved = []
    for stamp in stamps:
        target = os.path.join(outdir, "frame_%04d.png" % stamp)
        try:
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(stamp), "-i", video,
                 "-vf", "subtitles=%s:force_style=Fontsize=48" % name,
                 "-frames:v", "1", target], cwd=cwd)
        except subprocess.CalledProcessError:
            continue
        if os.path.exists(target) and os.path.getsize(target) > 1000:
            saved.append(target)
    if saved:
        log("  captured %d frame(s) with the soft subtitle rendered" % len(saved))
    return saved


def cmd_plan(args):
    episodes = build_plan()
    log("  season 01 episodes: %d" % len(episodes))
    for ep in episodes:
        log("    ep %2d  idx %3d  %s"
            % (ep["episode"], ep["index"], ep["path"].split("/")[-1]))
    return 0


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
        "JoJo's Bizarre Adventure (2012) - 1080p, English subtitles (soft track)",
        "",
        "Episodes 1-9: Phantom Blood",
        "Episodes 10-26: Battle Tendency",
        "",
        "Source: Anime Time BD repackage (1080p HEVC 10-bit, dual audio, English soft subs)",
        "The video and both audio tracks are stream copied, so the picture is the",
        "source quality. The English subtitle track is muxed in as a soft track and",
        "has to be switched on in the player.",
    ])
    rel = create_release(owner, repo, args.tag,
                         "JoJo 2012 1080p English Soft Subs (Episodes 1-26)", body)
    log("  tag: %s  id: %s" % (args.tag, rel["id"]))
    emit("release_id", str(rel["id"]))
    emit("release_tag", args.tag)
    emit("release_url", rel["html_url"])
    return 0


def cmd_episode(args):
    episodes = build_plan()
    match = [ep for ep in episodes if ep["episode"] == args.episode]
    if not match:
        raise SystemExit("::error::Episode %d is not in the torrent" % args.episode)
    ep = match[0]

    owner, repo = repo_parts()
    root = workdir_root()
    workdir = os.path.join(root, "jojo-ep%02d-1080p" % args.episode)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    try:
        torrent = os.path.join(workdir, "source.torrent")
        fetch_torrent(torrent)
        source = download_episode(torrent, ep["index"], os.path.join(workdir, "src"),
                                  args.episode)

        source_data = probe(source)
        source_duration = video_duration(source_data)
        log("  source: %.0f s container, %.0f s video track"
            % (float(source_data.get("format", {}).get("duration", 0) or 0), source_duration))
        chosen = pick_subtitle(source, args.subtitle_track)

        ass = extract_subtitle(source, os.path.join(workdir, "subs.ass"), chosen["index"])
        require_english(ass, "source subtitle track")

        output = remux(source, os.path.join(workdir, "out.mp4"), chosen["index"])
        verify_output(output, source_duration)

        srt = extract_soft_subtitle(output, os.path.join(workdir, "soft.srt"))
        require_english(srt, "muxed soft subtitle track")

        frame_dir = os.environ.get("JOJO_FRAME_DIR") or os.path.join(workdir, "frames")
        capture_frames(output, srt, frame_dir)

        name = ASSET_TEMPLATE % args.episode
        log("  uploading %s" % name)
        upload_asset(owner, repo, args.release_id, name, output)
        log("  uploaded")
        emit("uploaded_asset", name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


def cmd_m3u(args):
    owner, repo = repo_parts()
    episodes = [{"index": n, "filename": ASSET_TEMPLATE % n} for n in range(1, 27)]

    # Never point the playlist at a release that is missing episodes.
    present = release_asset_names(owner, repo, args.tag)
    wanted = [ep["filename"] for ep in episodes]
    missing = [name for name in wanted if name not in present]
    if missing:
        raise SystemExit("::error::Release %s is missing %d asset(s): %s"
                         % (args.tag, len(missing), ", ".join(missing[:6])))
    log("  release holds all %d episode assets" % len(wanted))

    base_url = "https://github.com/%s/%s/releases/download/%s" % (owner, repo, args.tag)
    write_m3u(args.out, episodes, base_url)
    emit("m3u_file", os.path.abspath(args.out))
    emit("episode_count", str(len(episodes)))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
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
    episode.add_argument("--subtitle-track", type=int,
                         default=int(os.environ.get("SUBTITLE_TRACK", "3")))
    episode.set_defaults(func=cmd_episode)

    m3u = sub.add_parser("m3u")
    m3u.add_argument("--tag", required=True)
    m3u.add_argument("--out", default="jojo2012-1080p.m3u")
    m3u.set_defaults(func=cmd_m3u)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
