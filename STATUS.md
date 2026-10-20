# JoJo 2012 — English Subtitle Build — Status

Last updated: 2026-10-20 10:25 UTC

## Goal

Replace the Indonesian hardsubbed 2012 episodes with English-subtitled ones, in
`NanoBotAgent/jojo2012-m3u-generator`. The released MP4s are the deliverable;
the M3U points at them.

## Current state

| Item | Status |
|---|---|
| Source identified | DONE — Anime Time, nyaa 1681123, 125 seeders, confirmed live |
| English subs confirmed | DONE — 7 subtitle tracks, all English-tagged; dialogue text verified |
| Download path proven | DONE — 40 MB/s, episode 01 fetched intact (456 MiB) |
| Pipeline written | DONE — `scripts/torrent_release.py` + `download-english-and-release.yml` |
| Torrent metadata bug | FIXED — see below |
| M3U safety guard | DONE — partial builds can no longer repoint the M3U |
| Pilot run (episode 1) | IN PROGRESS — run 39405815136, transcode step still running |
| Full 26-episode build | NOT STARTED — blocked on the pilot |
| M3U regeneration | NOT STARTED — gated on the full build |
| Old Indonesian release | UNTOUCHED — tag `jojo2012-720p-29` still live |

## Source of record

- **Torrent**: `https://nyaa.si/view/1681123` — `[Anime Time] JoJo's Bizarre
  Adventure (S01-05) (Part 01-06)` — 125 seeders, 7152 completions.
- **Season 01** = the 2012 series, 26 files, aria2 indices 14–39.
- **Streams** (verified with ffprobe on a real download, run 39362540027):
  - video: HEVC 1920x1080, 10-bit
  - audio: AAC English (index 1) + AAC Japanese (index 2)
  - subtitles: 7 tracks, all tagged `eng` — soft ASS `inid4c + SFX` (index 3),
    `Some-Stuffs + SFX` (4), `inid4c` (5), Blu-ray PGS (6, 7, 8), and
    `Signs & Songs (inid4c + SFX)` (9)
- **Verified dialogue** from index 3: *"Oy, look at this! There's been an
  accident!"*

## Decisions taken

- **D1 — source**: Anime Time over the alternatives. Judas also has live seeds
  and English subs but its filenames are inconsistent between the 2012 and
  2013 seasons, and the same swap-axes episode numbering is easy to get
  wrong. The hchcsen release has English soft subs but 10 of its 26 files
  exceed the 2 GB release-asset limit. Anime Time is the only candidate with
  both live seeds and every file under the limit.
- **D2 — burn the subs in.** The previous release was hardsubbed MP4, so
  burning keeps the deliverable shape identical. It also works in every
  player, including the box's ffmpeg and any IPTV app, with no subtitle
  track support required.
- **D3 — English audio.** The source ships an English audio track, so the
  result is watchable in English with no further work.
- **D4 — track 3** (`inid4c + SFX`) is the burn source: dialogue plus signs
  plus effects, which is the complete set.
- **D5 — 720p H.264 output.** The source is 1080p HEVC 10-bit, which is a
  poor fit for an IPTV client and would roughly double the bandwidth. Same
  resolution and codec family as the old release.

## Bugs found and fixed

### The torrent metadata lies about file sizes

The `files` array in the torrent declares lengths that are offset from the
files the swarm actually serves. My own size check was rejecting correct
downloads.

Fix: use `aria2c --show-files` as the index source, since `--select-file` is
resolved against exactly that list; match the downloaded file by path, not by
size; and verify the result with ffprobe (duration plus track list) instead of
comparing byte counts. Commit `9604095`.

The listing has been seen in both the `IDX|PATH` and `IDX|PATH|SIZE` shapes,
so the parser now picks whichever field carries a file extension. Commit
`319bc97`.

### A partial build could have broken the working M3U

`cmd_m3u` built the playlist from a hardcoded list of 26 filenames without
checking that the release actually contained them. A build that failed partway
would have repointed the M3U at missing assets.

Fix: `cmd_m3u` lists the release's assets and refuses to write the playlist
unless all 26 are present. The `m3u` job is additionally skipped unless the
build covered the full 1–26 set. Commit `319bc97`.

### ffmpeg could not find the subtitle file

The transcode passed a bare `subs.ass` to the filter but ran ffmpeg from the
checkout directory, where that name does not exist.

Fix: run ffmpeg from the work directory that holds the extracted file. A bare
name also avoids the filter-syntax escaping problems that a full work path
would cause. Commit `319bc97`.

### Earlier, in the original release pipeline

- `python3 download.py >> $GITHUB_OUTPUT` — all stdout went into
  `$GITHUB_OUTPUT`, which only accepts `key=value`. Fixed by writing to a
  file and reading it.
- `urls[resolution]` with `github.event.inputs.resolution` — empty on a push
  event. Fixed by using a dispatch input.
- `videos/*.mp4` pathspec — matched nothing when `VIDEO_URLS` was unset.
- Four workflow files were not valid YAML at all, so GitHub registered them
  with zero triggers. Fixed in commit `d15669e`.
- The 720p batch ZIP is 6.23 GB, not 2.9 GB, and the old step unzipped *and*
  copied, needing about 18.6 GB. Rebuilt to extract one episode at a time.

## Next tasks

1. **Watch the pilot** (run 39405815136). Confirm:
   - the episode downloads and the right file is picked,
   - the transcode completes and how long it takes (this sets the budget for
     26 parallel jobs),
   - the output has burned-in English subs and an English audio track,
   - the sample frames show readable English text.
2. **Decide on the build shape** based on the measured transcode time:
   - one job per episode (26 jobs, ~20 min each) — fastest wall clock, but 26
     concurrent downloads of the same torrent;
   - a few jobs each doing several episodes — gentler on the swarm, slower.
3. **Run the full 1–26 build** and confirm the release holds all 26 assets.
4. **Regenerate the M3U** and confirm it points at the new release.
5. **Verify externally**: fetch one asset, ffprobe it for the English audio
   track, and confirm the burned-in subtitles by extracting frames.
6. **Decide what to do with the old Indonesian release** — leave it, or delete
   it once the new one is confirmed good.
7. **Consider a rolling publish** — upload each episode to the release as it
   finishes rather than waiting for all 26.

## How to check a run

```bash
export GH_TOKEN="$(cat /home/applepie69/.github-token)"
RUN=<run-id>
curl -sS --max-time 60 -H "Authorization: Bearer $GH_TOKEN" \
  "https://api.github.com/repos/NanoBotAgent/jojo2012-m3u-generator/actions/runs/$RUN/jobs" \
  | python3 -c "
import json,sys
for j in json.load(sys.stdin).get('jobs',[]):
    print('  %-14s %-10s %s' % (j['name'], j['status'], j.get('conclusion')))
"
```

Job logs are only downloadable once the job finishes; the endpoint returns
`BlobNotFound` while it is still running.

## Local resource note

The VPS has 2 GB of tmpfs and a low memory ceiling, so no local build, no
local torrent download, and no local transcode. Everything heavy runs on
GitHub Actions runners.
