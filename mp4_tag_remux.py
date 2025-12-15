#!/usr/bin/env python3
"""Simple MP4 remux + tagging helper that calls ffmpeg.

Usage examples:
  python mp4_tag_remux.py input.mp4 output.mp4 --tag title="My Title" --tag comment="Notes"
  python mp4_tag_remux.py in.mp4 out.mp4 --tag title=Movie --lang a:0=eng --dry-run

Requires: ffmpeg on PATH.
"""
import argparse
import shutil
import subprocess
import sys


def build_ffmpeg_cmd(infile, outfile, tags, langs, extra_args):
    cmd = ["ffmpeg"]
    cmd += ["-i", infile]
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
        cmd += [f"-metadata:s:{stream_type}:{index}", f"language={lang}"]

    # Extra raw ffmpeg args (passed through)
    if extra_args:
        cmd += extra_args

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
    parser.add_argument("outfile", help="Output MP4 file")
    parser.add_argument("--tag", "-t", action="append", default=[],
                        help="Metadata tag in KEY=VALUE format; can be repeated")
    parser.add_argument("--lang", "-l", action="append", default=[],
                        help="Per-stream language in STREAM:INDEX=LANG (e.g. a:0=eng); can be repeated")
    parser.add_argument("--ffmpeg-arg", action="append", default=[],
                        help="Extra raw ffmpeg arg (each instance added verbatim)")
    parser.add_argument("--dry-run", action="store_true", help="Print ffmpeg command without running")

    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found on PATH. Install ffmpeg and ensure it's available.", file=sys.stderr)
        sys.exit(2)

    try:
        tags = parse_keyvals(args.tag)
        langs = parse_langs(args.lang)
    except argparse.ArgumentTypeError as e:
        parser.error(str(e))

    ffmpeg_cmd = build_ffmpeg_cmd(args.infile, args.outfile, tags, langs, args.ffmpeg_arg)

    if args.dry_run:
        print("Dry run; ffmpeg command:")
        print(" ".join(subprocess.list2cmdline([c]) for c in ffmpeg_cmd))
        return

    print("Running:", " ".join(ffmpeg_cmd))
    proc = subprocess.run(ffmpeg_cmd)
    if proc.returncode != 0:
        print(f"ffmpeg exited with {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
