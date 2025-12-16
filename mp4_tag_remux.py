#!/usr/bin/env python3
"""Simple MP4 remux + tagging helper that calls ffmpeg.

Usage examples:
  python mp4_tag_remux.py input.mp4 output_dir --tag title="My Title" --tag comment="Notes"
  python mp4_tag_remux.py in.mp4 out_dir --tag title=Movie --lang a:0=eng --dry-run
  python mp4_tag_remux.py in.mp4 out_dir --tmdb-id 550 --tmdb-key YOUR_KEY

Note: when using --tmdb-id the second positional is an output directory; the TMDB title
will be used as the output filename (sanitized) with a .mp4 extension.

Requires: ffmpeg on PATH.
"""
import argparse
import shutil
import subprocess
import sys
import os
import tempfile
import json
import urllib.request
import urllib.error
import re

def fetch_tmdb_poster(tmdb_id, api_key):
    """Fetch poster image from TMDB and return tuple (local temp file path, title)."""
    api_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}"
    try:
        with urllib.request.urlopen(api_url) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"TMDB API error: {e}") from e
    poster_path = data.get("poster_path")
    title = data.get("title") or data.get("original_title") or f"tmdb_{tmdb_id}"
    if not poster_path:
        raise RuntimeError("No poster_path found for TMDB id")
    img_url = f"https://image.tmdb.org/t/p/original{poster_path}"
    suffix = os.path.splitext(poster_path)[1] or ".jpg"
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tf.close()
    try:
        urllib.request.urlretrieve(img_url, tf.name)
    except Exception as e:
        try:
            os.unlink(tf.name)
        except Exception:
            pass
        raise RuntimeError(f"Failed to download poster image: {e}") from e
    return tf.name, title

def sanitize_filename(name, max_len=255):
    """Sanitize a string to be a safe filename on Windows/Unix."""
    # remove control chars
    name = re.sub(r"[\x00-\x1f]", "", name)
    # replace forbidden chars <>:"/\\|?*
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip().rstrip(".")
    if not name:
        name = "output"
    if len(name) > max_len:
        name = name[:max_len]
    return name


def build_ffmpeg_cmd(infile, outfile, tags, langs, extra_args, poster_file=None):
    cmd = ["ffmpeg"]
    # Input files
    cmd += ["-i", infile]
    if poster_file:
        cmd += ["-i", poster_file]

    # Mapping and codecs
    # If poster provided, map input and poster and mark poster as attached_pic (mjpeg)
    if poster_file:
        cmd += ["-map", "0", "-map", "1"]
        cmd += ["-c", "copy", "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic"]
    else:
        cmd += ["-c", "copy"]

    # Global metadata tags
    for k, v in tags.items():
        cmd += ["-metadata", f"{k}={v}"]

    # Per-stream language metadata entries (format: "a:0=eng")
    for spec, lang in langs.items():
        # spec looks like "a:0" or "v:0"
        stream_type, _, index = spec.partition(":")
        if not index:
            raise ValueError(f"Invalid stream spec: {spec}")
        # ffmpeg expects: -metadata:s:<stream_type>:<index> language=<lang>
        cmd += [f"-metadata:s:{stream_type}:{index}", f"language={lang}"]

    # Extra raw ffmpeg args (passed through)
    if extra_args:
        cmd += list(extra_args)

    cmd += ["-y", outfile]
    return cmd


def parse_keyvals(items):
    result = {}
    if not items:
        return result
    for it in items:
        if "=" not in it:
            raise argparse.ArgumentTypeError(f"Expected KEY=VALUE format, got: {it}")
        k, v = it.split("=", 1)
        result[k] = v
    return result


def parse_langs(items):
    # Accept items like "a:0=eng" or "v:1=spa"
    result = {}
    if not items:
        return result
    for it in items:
        if "=" not in it:
            raise argparse.ArgumentTypeError(f"Expected STREAM:INDEX=LANG, got: {it}")
        left, lang = it.split("=", 1)
        if ":" not in left:
            raise argparse.ArgumentTypeError(f"Expected STREAM:INDEX on left side, got: {left}")
        result[left] = lang
    return result


def main():
    parser = argparse.ArgumentParser(description="Remux MP4 and apply tags via ffmpeg (-metadata).")
    parser.add_argument("infile", help="Input MP4 file")
    parser.add_argument("outpath", help="Output directory (when using --tmdb-id) or output file path")
    parser.add_argument("--tag", "-t", action="append", default=[],
                        help="Metadata tag in KEY=VALUE format; can be repeated")
    parser.add_argument("--lang", "-l", action="append", default=[],
                        help="Per-stream language in STREAM:INDEX=LANG (e.g. a:0=eng); can be repeated")
    parser.add_argument("--ffmpeg-arg", action="append", default=[],
                        help="Extra raw ffmpeg arg (each instance added verbatim)")
    parser.add_argument("--dry-run", action="store_true", help="Print ffmpeg command without running")
    parser.add_argument("--poster-file", help="Local image file to embed as poster (attached_pic)")
    parser.add_argument("--tmdb-id", type=int, help="TMDB movie id to fetch poster for")
    parser.add_argument("--tmdb-key", help="TMDB API key (or set TMDB_API_KEY env var)")

    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found on PATH. Install ffmpeg and ensure it's available.", file=sys.stderr)
        sys.exit(2)

    try:
        tags = parse_keyvals(args.tag)
        langs = parse_langs(args.lang)
    except argparse.ArgumentTypeError as e:
        parser.error(str(e))

    poster_file = None
    poster_temp_created = False
    tmdb_title = None

    if args.poster_file and args.tmdb_id:
        parser.error("Specify either --poster-file or --tmdb-id, not both")

    if args.poster_file:
        if not os.path.exists(args.poster_file):
            print(f"Poster file not found: {args.poster_file}", file=sys.stderr)
            sys.exit(2)
        poster_file = args.poster_file

    if args.tmdb_id:
        api_key = args.tmdb_key or os.environ.get("TMDB_API_KEY")
        if not api_key:
            parser.error("TMDB API key required (use --tmdb-key or set TMDB_API_KEY env var)")
        try:
            poster_file, tmdb_title = fetch_tmdb_poster(args.tmdb_id, api_key)
            poster_temp_created = True
        except Exception as e:
            print(f"Failed to fetch poster from TMDB: {e}", file=sys.stderr)
            sys.exit(2)

    # Determine outfile path:
    if args.tmdb_id:
        # treat outpath as directory; create if needed
        outdir = args.outpath
        if not os.path.isdir(outdir):
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                print(f"Failed to create output directory '{outdir}': {e}", file=sys.stderr)
                if poster_temp_created and poster_file:
                    try:
                        os.unlink(poster_file)
                    except Exception:
                        pass
                sys.exit(2)
        safe_name = sanitize_filename(tmdb_title)
        outfile = os.path.join(outdir, f"{safe_name}.mp4")
    else:
        # outpath is treated as full output filename
        outfile = args.outpath

    ffmpeg_cmd = build_ffmpeg_cmd(args.infile, outfile, tags, langs, args.ffmpeg_arg, poster_file=poster_file)

    if args.dry_run:
        print("Dry run; ffmpeg command:")
        print(" ".join(ffmpeg_cmd))
        print("Output will be:", outfile)
        # cleanup temp poster if downloaded
        if poster_temp_created and poster_file:
            try:
                os.unlink(poster_file)
            except Exception:
                pass
        return

    print("Running:", " ".join(ffmpeg_cmd))
    proc = subprocess.run(ffmpeg_cmd)
    if proc.returncode != 0:
        print(f"ffmpeg exited with {proc.returncode}", file=sys.stderr)
        if poster_temp_created and poster_file:
            try:
                os.unlink(poster_file)
            except Exception:
                pass
        sys.exit(proc.returncode)

    # cleanup temp poster if downloaded
    if poster_temp_created and poster_file:
        try:
            os.unlink(poster_file)
        except Exception:
            pass


if __name__ == "__main__":
    main()