MP4 Tag & Remux Helper

This small utility wraps `ffmpeg` to remux MP4 files (`-c copy`) and apply metadata tags using `-metadata` and per-stream language metadata.

Prerequisites
- `ffmpeg` available on PATH (download from https://ffmpeg.org/)
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
