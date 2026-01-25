MP4 Tag & Remux Helper

This small utility wraps `ffmpeg` to remux MP4 files (`-c copy`) and apply metadata tags using `-metadata` and per-stream language metadata.

Prerequisites
- `ffmpeg` available on PATH (download from https://ffmpeg.org/)
- `ffprobe` available on PATH (used to detect subtitle streams)
- `HandBrakeCLI` available on PATH (required for `hb_transcode.py`) or supply `--handbrake` with a path to the binary
- `pgsrip` available on PATH (optional; used to extract PGS/bitmap subtitles when present)
- Python 3.7+

Usage

```bash
python mp4_tag_remux.py input.mp4 output.mp4 --tag title="My Title" --tag comment="Notes"

# Set audio stream 0 language to English
python mp4_tag_remux.py in.mp4 out.mp4 --tag title=Demo --lang a:0=eng

# Dry run (print ffmpeg command)
python mp4_tag_remux.py in.mp4 out.mp4 --tag title=Test --dry-run
```

Advanced
- Use `--ffmpeg-arg` to pass raw ffmpeg options (repeated as needed).
- Per-stream language uses format `STREAM:INDEX=LANG` where STREAM is `a` (audio), `v` (video), or `s` (subtitle).

Examples

- Remux and set title + comment:

```bash
python mp4_tag_remux.py movie_src.mp4 movie_tagged.mp4 --tag title="My Movie" --tag comment="Remuxed on 2025-12-15"
```

- Set audio language on first audio track and add album tag:

```bash
python mp4_tag_remux.py src.mp4 dst.mp4 -t album=MyAlbum -l a:0=eng
```

**hb_transcode.py**

Transcode .mkv files to .mp4 using HandBrakeCLI. Examples below show subtitle extraction and recursive behavior.

```bash
# Single-directory: transcode and extract English subtitles alongside the MP4
python hb_transcode.py --input /path/to/mkvs --output /path/to/out --preset "Fast 1080p30" --extract-subs

# Recursive: process all .mkv under input, preserving directory tree under output
python hb_transcode.py --input "/path/with spaces" --output /out/dir --preset "Fast 1080p30" --recursive --extract-subs

# Dry-run: preview actions (no HandBrakeCLI/ffmpeg/pgsrip executed)
python hb_transcode.py --input samples --output out --preset "Fast 1080p30" --dry-run --extract-subs
```

Notes:
- `--extract-subs` attempts to extract an English subtitle stream. For PGS (bitmap) subtitles the script may call `pgsrip`, which commonly writes `<input_basename>.en.srt` next to the input MKV; the script will move that file to the MP4 output location and name it `<mp4_basename>.default.srt`.
- Use `--handbrake` to supply a custom HandBrakeCLI path if it's not on `PATH`.
