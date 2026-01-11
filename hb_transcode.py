#!/usr/bin/env python3
"""Transcode MKV files to MP4 using HandBrakeCLI.

Usage:
  python hb_transcode.py --input INPUT_DIR --output OUTPUT_DIR --preset "Fast 1080p30" [--recursive] [--handbrake PATH] [--dry-run]

For each .mkv file in INPUT_DIR (or recursively if --recursive), the script
creates an MP4 in OUTPUT_DIR with the same basename and invokes HandBrakeCLI:
  HandBrakeCLI -i <in> -o <out> -Z "<preset>"

Requires HandBrakeCLI available on PATH or provided via --handbrake.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from typing import List


def find_mkvs(input_dir: str, recursive: bool = False) -> List[str]:
    pattern = "*.mkv"
    if recursive:
        matches = []
        for root, _, files in os.walk(input_dir):
            for f in files:
                if f.lower().endswith('.mkv'):
                    matches.append(os.path.join(root, f))
        return sorted(matches)
    else:
        return sorted([os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.lower().endswith('.mkv')])


def ensure_output_path(output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)


def safe_output_path(output_dir: str, base_name: str) -> str:
    """Return a non-colliding output path with .mp4 extension."""
    candidate = os.path.join(output_dir, base_name + '.mp4')
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate2 = os.path.join(output_dir, f"{base_name}-{i}.mp4")
        if not os.path.exists(candidate2):
            return candidate2
        i += 1


def find_handbrake_cli(override: str | None = None) -> str | None:
    if override:
        return override
    hb = shutil.which('HandBrakeCLI') or shutil.which('HandBrakeCLI.exe')
    return hb


def transcode_one(hb_path: str, infile: str, outfile: str, preset: str, dry_run: bool = False) -> int:
    cmd = [hb_path, '-i', infile, '-o', outfile, '-Z', preset]
    cmd_str = ' '.join(f'"{p}"' if ' ' in p else p for p in cmd)
    logging.info('Running: %s', cmd_str)
    if dry_run:
        return 0
    try:
        # capture output so we can log it
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.stdout:
            logging.info(proc.stdout)
        if proc.stderr:
            logging.error(proc.stderr)
        return proc.returncode
    except FileNotFoundError:
        logging.error('HandBrakeCLI executable not found at %s', hb_path)
        return 2


def embed_mp4_title(mp4_path: str, title: str) -> bool:
    """Use ffmpeg to set the MP4 title metadata without re-encoding (copy streams).

    Returns True on success, False otherwise.
    """
    ffmpeg = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if not ffmpeg:
        logging.warning('ffmpeg not available; cannot embed title metadata for %s', mp4_path)
        return False

    dirn = os.path.dirname(mp4_path)
    base = os.path.splitext(os.path.basename(mp4_path))[0]
    tmp = os.path.join(dirn, base + '.tmp.mp4')
    # If the input filename uses " - " as a separator, treat the first instance
    # as a visual separator and convert it to ": " in the embedded title.
    metadata_title = title.replace(' - ', ': ', 1)
    cmd = [ffmpeg, '-i', mp4_path, '-c', 'copy', '-metadata', f'title={metadata_title}', tmp, '-y']
    logging.info('Embedding title metadata: %s (from input: %s)', metadata_title, title)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.stdout:
            logging.info(p.stdout)
        if p.stderr:
            logging.info(p.stderr)
        if p.returncode == 0 and os.path.exists(tmp):
            try:
                os.replace(tmp, mp4_path)
                logging.info('Embedded title into %s', mp4_path)
                return True
            except Exception as e:
                logging.error('Failed to replace temp file for %s: %s', mp4_path, e)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return False
        else:
            logging.error('ffmpeg failed to embed title for %s (exit %s)', mp4_path, p.returncode)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False
    except FileNotFoundError:
        logging.error('ffmpeg executable not found at %s', ffmpeg)
        return False


def main():
    parser = argparse.ArgumentParser(description='Transcode MKV files to MP4 using HandBrakeCLI')
    parser.add_argument('--input', '-i', required=True, help='Input directory containing .mkv files')
    parser.add_argument('--output', '-o', required=True, help='Output directory for .mp4 files')
    parser.add_argument('--preset', '-p', required=True, help='HandBrake preset name (pass to -Z). Example: "Fast 1080p30"')
    parser.add_argument('--recursive', '-r', action='store_true', help='Recursively find .mkv files under input')
    parser.add_argument('--handbrake', help='Path to HandBrakeCLI executable (optional)')
    parser.add_argument('--dry-run', action='store_true', help='Show commands without executing')

    args = parser.parse_args()

    input_dir = args.input
    output_dir = args.output
    preset = args.preset
    recursive = args.recursive
    hb_override = args.handbrake
    dry_run = args.dry_run

    # prepare logging to file + console
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(script_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    import datetime
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    logfile = os.path.join(logs_dir, f'hb_transcode_{ts}.log')

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')

    fh = logging.FileHandler(logfile, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    logging.info('hb_transcode starting; input=%s output=%s preset=%s recursive=%s dry_run=%s', input_dir, output_dir, preset, recursive, dry_run)

    if not os.path.isdir(input_dir):
        logging.error('Input directory not found: %s', input_dir)
        sys.exit(2)

    if dry_run:
        logging.info('Dry-run: would create output root: %s', output_dir)
    else:
        ensure_output_path(output_dir)

    hb = find_handbrake_cli(hb_override)
    if not hb:
        logging.error('HandBrakeCLI not found on PATH and no --handbrake override provided.')
        sys.exit(2)

    mkvs = find_mkvs(input_dir, recursive=recursive)
    if not mkvs:
        logging.info('No .mkv files found in %s', input_dir)
        return

    failures = 0
    successes = 0
    total = len(mkvs)
    # When recursive, preserve the input directory tree under the output root.
    input_dir_abs = os.path.abspath(input_dir)
    for mkv in mkvs:
        mkv_dir = os.path.dirname(os.path.abspath(mkv))
        if recursive:
            rel_dir = os.path.relpath(mkv_dir, input_dir_abs)
            # relpath returns '.' when file is directly in input_dir
            if rel_dir == '.' or rel_dir == os.curdir:
                target_dir = output_dir
            else:
                target_dir = os.path.join(output_dir, rel_dir)
        else:
            target_dir = output_dir

        if dry_run:
            logging.info('Dry-run: would create target directory: %s', target_dir)
        else:
            ensure_output_path(target_dir)
        base = os.path.splitext(os.path.basename(mkv))[0]
        outpath = safe_output_path(target_dir, base)
        ret = transcode_one(hb, mkv, outpath, preset, dry_run=dry_run)
        # In dry-run, preview the embedded title that would be written.
        if dry_run and ret == 0:
            metadata_title = base.replace(' - ', ': ', 1)
            logging.info('Dry-run: would create MP4: %s', outpath)
            logging.info('Dry-run: would embed title: %s', metadata_title)
        if ret != 0:
            logging.error('Transcode failed for %s (exit %s)', mkv, ret)
            failures += 1
        else:
            successes += 1
            # embed input filename as MP4 title metadata (if not dry-run)
            if not dry_run:
                try:
                    embed_mp4_title(outpath, base)
                except Exception as e:
                    logging.warning('Failed to embed title for %s: %s', outpath, e)

    logging.info('Summary: total=%d, succeeded=%d, failed=%d', total, successes, failures)
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
