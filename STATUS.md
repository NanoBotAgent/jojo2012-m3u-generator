# JoJo's Bizarre Adventure (2012) - English Subtitle Pipeline

Status document. Findings, decisions, and remaining work live here so progress
survives a crash or a context reset.

Last updated: 2026-10-20

## Goal

The released episodes carry **Indonesian** subtitles. The user wants **English**
subtitles, and prefers the simplest route that works.

Current playlist: `jojo2012-720p.m3u` -> release `jojo2012-720p-29`
(26 assets, `Alqanime_Jojo_BD_XX_720p.mp4`).

## Findings

### F1. The current release has hardcoded (burned-in) subtitles, not a subtitle track

Verified by pulling the `moov` atom out of the released MP4 over HTTP range
requests and walking its track list (`Alqanime_Jojo_BD_01_720p.mp4`,
216,867,603 bytes):

```
handler=vide   lang=0x55c40000
handler=soun   lang=0x55c40000
```

One video track, one audio track, **zero** subtitle tracks. The Indonesian text
is pixels in the picture. Consequences:

- Muxing an English `.srt` into the *existing* files would show both languages
  at once. Not a fix.
- The only way to change the language of those files is a different source.
- A sidecar `.srt` next to the `.mp4` is also not a fix for streaming clients:
  IPTV players do not fetch sidecar subs for a remote URL.

Therefore: **new source, not a subtitle hack.**

### F2. Source survey (all checked 2026-10-20)

| Source | Resolution | English subs | Verdict |
|---|---|---|---|
| alqanime (current) | 720p | none (Indonesian burned in) | rejected |
| dlnime | 720p | none (Indonesian burned in) | rejected |
| SubsPlusPlease | - | only Stone Ocean (2022), not the 2012 series | rejected |
| AnimeRG 2016 "Multi Subbed" | 720p | had English | rejected: every mirror dead (multiup 000, nitroflare 404, sendspace 404, 1fichier 404, oboom timeout, solidfiles 000) |
| archive.org `JoJo_Episodes_DIO` / `JoJos_Bizzare_Adventure_2` | - | English | rejected: single concatenated 35 GB / 29 GB AVI, not per episode |
| Bunny Hat (nyaa 478730) | 720p BD | English PGS only | rejected: image-based subs, 0 bytes extractable, no text track |
| DmonHiro (nyaa 480153) | 720p BD | - | rejected: 36 files, S01 numbering mixed with extras |
| hchcsen (nyaa 1470445) | 1080p | English soft ASS | rejected: 46.77 GiB total, 10 files >= 2 GB (exceeds GitHub release-asset limit) |
| **Anime Time (nyaa 1681123)** | **1080p HEVC** | **7 English tracks** | **selected** |

### F3. Anime Time (nyaa 1681123) is verified good

Real `ffprobe` output from CI run 39362540027 on episode 1:

```
index=0  hevc  1920x1080
index=1  aac   TAG:language=eng  TAG:title=English
index=2  aac   TAG:language=jpn  TAG:title=Japanese
index=3  ass   TAG:language=eng  TAG:title=inid4c + SFX
index=4  ass   TAG:language=eng  TAG:title=Some-Stuffs + SFX
index=5  ass   TAG:language=eng  TAG:title=inid4c
index=6  hdmv_pgs_subtitle  1920x1080
index=7  hdmv_pgs_subtitle
index=8  hdmv_pgs_subtitle
index=9  ass   TAG:language=eng  TAG:title=Signs & Songs (inid4c + SFX)
```

Extracted dialogue from the English track is genuine English:

> "Oy, look at this! There's been an accident!"

Download works: 41 MiB/s, 475 MB for episode 1, live seeds, `aria2c
--select-file` pulls exactly one episode.

Season 01 is 26 files, aria2 indices **14-39**, 15.91 GiB total, every file
427-795 MB (all under the 2 GB GitHub release-asset limit).

### F4. Repo and box state

- Repo `NanoBotAgent/jojo2012-m3u-generator` is **private**, default branch `main`.
- Workflows: `download-720p-and-release.yml` (dispatch), `download-jojo-release.yml`
  (dispatch), `download-videos.yml` (push on main), `probe-subs.yml` (dispatch).
- `scripts/publish_release.py` already has reusable
  `create_release()` / `upload_asset()` / `write_m3u()` helpers and the
  `episode_titles.py` name table.
- The alwaysdata box (`proxy-iptv`) has **0** references to
  `jojo2012-m3u-generator` in `playlist.movies.m3u`, so the JoJo playlist is
  standalone and the box needs no change for this work.

## Decisions

- **D1. New source, new release.** Keep `jojo2012-720p-29` (Indonesian) intact
  as a fallback; publish a second release and repoint `jojo2012-720p.m3u` at it.
- **D2. Burn the English subs in.** Sidecar `.srt` and embedded soft tracks
  were both rejected: IPTV clients playing a remote URL do not load sidecar
  subs, and soft-sub tracks are off by default in most players. Burned-in is
  what the current release already does, only in the right language.
- **D3. 720p H.264 output, same as today.** The source is 1080p HEVC 10-bit;
  downscale to 720p H.264 so the deliverable keeps the current format, codec,
  and rough size, and streams comfortably.
- **D4. Japanese audio, English subs.** The inid4c subs are timed to the
  Japanese track. The release also carries an English dub track, but subtitle
  timing would not match it, so it is not used.
- **D5. One CI job per episode, matrixed.** `aria2c --select-file` downloads a
  single episode, so 26 jobs can run in parallel with no shared disk pressure
  and no multi-GB serial pull.
- **D6. New workflow is `workflow_dispatch` only.** The old unbounded
  re-download loop (release URL contains the run number, M3U commit retriggers
  the workflow) is avoided by never triggering on push.

## Task list

- [x] Verify the current release really has no subtitle track (F1)
- [x] Survey every candidate source for per-episode English subs (F2)
- [x] Verify the Anime Time release with real ffprobe output (F3)
- [x] Decide source, delivery format, and CI shape (D1-D6)
- [x] Write `scripts/torrent_release.py` (plan / episode / m3u subcommands)
- [x] Write `.github/workflows/download-english-and-release.yml`
- [x] Push to `main`
- [ ] **Pilot: build episode 1 only, measure transcode time and check the frame**
- [ ] **Full run: all 26 episodes**
- [ ] Verify the output release: 26 assets, all 720p H.264, English burned in
- [ ] Repoint `jojo2012-720p.m3u` at the new release and confirm it in the repo
- [ ] Report final M3U URL to the user

## Notes and constraints

- **CI minutes.** The repo is private. Each episode job is one download plus
  one 720p transcode, so the full run is the main cost. Pilot first to get a
  real number before committing to 26.
- **Licensing.** Anime Time is a release-group repackage of the Japanese BD with
  fansub English tracks - the same category of source as the alqanime batch
  already in use here. Flagged once for the record; the user chose to proceed.
- **Do not** touch the alwaysdata box for this task (the user said so
  explicitly). The JoJo playlist is not wired into the box.
- **Do not** delete the existing `jojo2012-720p-29` release.
- Runner disk: pick the work directory by measured free space, like
  `publish_release.py` already does, and delete each episode after upload.
