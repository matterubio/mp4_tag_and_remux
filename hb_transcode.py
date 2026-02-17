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
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import List
from pgsrip import pgsrip, Mkv, Options
from babelfish import Language

def find_mkvs(input_dir: str, recursive: bool = False) -> List[str]:
    pattern = "*.mkv"

    def _path_contains_ignored_dir(path: str) -> bool:
        try:
            rel = os.path.relpath(path, input_dir)
        except Exception:
            rel = path
        parts = rel.split(os.sep)
        for p in parts:
            if p in ('.', ''):
                continue
            if p.lower().startswith('ignore'):
                return True
        return False

    if recursive:
        matches = []
        for root, dirs, files in os.walk(input_dir):
            # Prune directories we should ignore so os.walk doesn't descend into them
            dirs[:] = [d for d in dirs if not d.lower().startswith('ignore')]
            if _path_contains_ignored_dir(root):
                continue
            for f in files:
                if f.lower().endswith('.mkv'):
                    matches.append(os.path.join(root, f))
        return sorted(matches)
    else:
        # If the input directory itself is an ignored folder, return empty
        if _path_contains_ignored_dir(input_dir):
            return []
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
    # Ensure HandBrake includes all English audio tracks from the source
    # `--audio-lang-list eng` restricts to English; `--all-audio` ensures all matching
    # audio streams are kept rather than just a single default.
    cmd = [
        hb_path,
        '-i', infile,
        '-o', outfile,
        '-Z', preset,
        '--audio-lang-list', 'eng',
        '--all-audio'
        ]
    cmd_str = ' '.join(f'"{p}"' if ' ' in p else p for p in cmd)
    logging.info('Running: %s', cmd_str)
    if dry_run:
        return 0
    try:
        # capture output so we can log it
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        # Read the output line by line as it is generated
        while True:
            output = proc.stdout.readline()
            # If the line is empty and the process has finished, break the loop
            if not output and proc.poll() is not None:
                break
            if output:
                # Print the output in real-time, flushing the buffer immediately
                print(output.strip(), flush=True)
        # Continue once the process has finished
        if proc.stdout:
            logging.info(proc.stdout)
        if proc.stderr:
            logging.error(proc.stderr)
        return proc.returncode
    except FileNotFoundError:
        logging.error('HandBrakeCLI executable not found at %s', hb_path)
        return 2


def find_english_subtitle_info(infile: str) -> tuple[int, str] | None:
    """Return (relative_sub_index, codec_name) for the English subtitle stream.

    Uses ffprobe to inspect streams. Returns None if no English subtitle stream is found
    or ffprobe isn't available.
    """
    ffprobe = shutil.which('ffprobe') or shutil.which('ffprobe.exe')
    if not ffprobe:
        logging.debug('ffprobe not found; cannot inspect subtitles for %s', infile)
        return None
    cmd = [ffprobe, '-v', 'error', '-print_format', 'json', '-show_streams', infile]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        # Read the output line by line as it is generated
        while True:
            output = p.stdout.readline()
            # If the line is empty and the process has finished, break the loop
            if not output and p.poll() is not None:
                break
            if output:
                # Print the output in real-time, flushing the buffer immediately
                print(output.strip(), flush=True)
        # Continue once the process has finished
        if p.returncode != 0 or not p.stdout:
            logging.debug('ffprobe failed for %s: %s', infile, p.stderr)
            return None
        data = json.loads(p.stdout)
    except Exception as e:
        logging.debug('ffprobe JSON parse error for %s: %s', infile, e)
        return None

    streams = data.get('streams', [])
    # First pass: prefer explicit language tag starting with 'en'
    sub_idx = 0
    for s in streams:
        if s.get('codec_type') == 'subtitle':
            tags = s.get('tags') or {}
            lang = (tags.get('language') or '').lower()
            if lang.startswith('en'):
                return sub_idx, s.get('codec_name', '')
            sub_idx += 1

    # Second pass: prefer disposition default
    sub_idx = 0
    for s in streams:
        if s.get('codec_type') == 'subtitle':
            disp = s.get('disposition') or {}
            if int(disp.get('default', 0)) == 1:
                return sub_idx, s.get('codec_name', '')
            sub_idx += 1

    return None


def extract_english_subtitles(infile: str, out_srt: str, dry_run: bool = False) -> bool:
    """Extract the first matching English subtitle stream to an SRT file (ffmpeg).

    The output filename should already end with ".default.srt".
    Returns True if an extraction was performed (or would be, in dry-run) and False otherwise.
    """
    info = find_english_subtitle_info(infile)
    if info is None:
        logging.info('No English subtitle stream found in %s', infile)
        return False
    rel_idx, codec = info

    ffmpeg = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if not ffmpeg:
        logging.warning('ffmpeg not available; cannot extract subtitles for %s', infile)
        # we may still be able to use pgsrip if installed and codec is pgs
    # If codec is PGS-like, prefer pgsrip extraction
    is_pgs = 'pgs' in (codec or '').lower() or 'hdmv' in (codec or '').lower()
    is_vobsub = 'vobsub' in (codec or '').lower() or 'dvd_subtitle' in (codec or '').lower()

    if dry_run:
        if is_pgs:
            logging.info('Dry-run: would extract PGS subtitles (codec=%s) from %s to %s using pgsrip', codec, infile, out_srt)
        elif is_vobsub:
            logging.info('Dry-run: would extract VOBSUB subtitles (codec=%s) from %s to %s using mkvmerge/mkvextract + SubtitleEdit', codec, infile, out_srt)
        else:
            logging.info('Dry-run: would extract subtitle stream %s from %s to %s using ffmpeg', rel_idx, infile, out_srt)
        return True

    if not is_pgs and is_vobsub:
        cmd = ['mkvmerge', '-J', infile]
        logging.info('Looking for English subtitles as VOBSUB with mkvmerge: %s', out_srt)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            # Read the output line by line as it is generated
            while True:
                output = p.stdout.readline()
                # If the line is empty and the process has finished, break the loop
                if not output and p.poll() is not None:
                    break
                if output:
                    # Print the output in real-time, flushing the buffer immediately
                    print(output.strip(), flush=True)
            # Continue once the process has finished
            if p.returncode != 0 or not p.stdout:
                logging.warning('mkvmerge failed for %s: %s', infile, p.stderr)
                return False
            data = json.loads(p.stdout)
            tracks = data.get('tracks', [])
            sub_tracks = [t for t in tracks if t.get('type') == 'subtitles']

            # Instead of relying on rel_idx, look for the first subtitle track with a language tag starting with 'en'
            track_id = None
            for t in sub_tracks:
                lang = t.get('properties', {}).get('language', {})
                if lang.startswith('en'):
                    track_id = t.get('id')
                    break
            if track_id is None:
                logging.warning('mkvmerge did not return an id for English subtitle stream index %s', infile)
                return False
            out_vobsub = os.path.splitext(out_srt)[0] + '.sub'
            extract_cmd = ['mkvextract', 'tracks', infile, f'{track_id}:{out_vobsub}']
            p2 = subprocess.Popen(extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            # Read the output line by line as it is generated
            while True:
                output = p2.stdout.readline()
                # If the line is empty and the process has finished, break the loop
                if not output and p2.poll() is not None:
                    break
                if output:
                    # Print the output in real-time, flushing the buffer immediately
                    print(output.strip(), flush=True)
            # Continue once the process has finished 
            if p2.returncode == 0 and os.path.exists(out_vobsub):
                logging.info('Wrote VobSub subtitles with mkvextract: %s', out_vobsub)
                subtitleedit = shutil.which('SubtitleEdit') or shutil.which('SubtitleEdit.exe')
                if subtitleedit:
                    se_cmd = [subtitleedit, '/convert', out_vobsub, 'srt', '/FixCommonErrors', f'/outputfilename:{out_srt}']
                    logging.info('Converting VobSub to SRT with SubtitleEdit: %s', out_srt)
                    try:
                        p3 = subprocess.Popen(se_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                        # Read the output line by line as it is generated
                        while True:
                            output = p3.stdout.readline()
                            # If the line is empty and the process has finished, break the loop
                            if not output and p3.poll() is not None:
                                break
                            if output:
                                # Print the output in real-time, flushing the buffer immediately
                                print(output.strip(), flush=True)
                        # Continue once the process has finished
                        if p3.returncode == 0 and os.path.exists(out_srt):
                            os.remove(out_vobsub)
                            os.remove(os.path.splitext(out_vobsub)[0] + '.idx')
                            logging.info('Converted VobSub to SRT: %s', out_srt)
                            return True
                        else:
                            logging.warning('SubtitleEdit failed to convert VobSub for %s (exit %s): %s', infile, p3.returncode, p3.stderr)
                    except FileNotFoundError:
                        logging.error('SubtitleEdit executable not found at %s', subtitleedit)
                else:
                    logging.warning('SubtitleEdit not found; extracted VobSub but cannot convert to SRT for %s', infile)
                return True
            else:
                logging.warning('mkvextract failed for %s: %s', infile, p2.stderr)
        except Exception as e:
            logging.warning('Failed to look for VobSub subtitles using mkvmerge for %s: %s', infile, e)

    # Try ffmpeg extraction for non-PGS streams
    if not is_pgs and ffmpeg:
        cmd = [ffmpeg, '-i', infile, '-map', f'0:s:{rel_idx}', '-c:s', 'srt', out_srt, '-y']
        logging.info('Extracting English subtitles with ffmpeg: %s', out_srt)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            # Read the output line by line as it is generated
            while True:
                output = p.stdout.readline()
                # If the line is empty and the process has finished, break the loop
                if not output and p.poll() is not None:
                    break
                if output:
                    # Print the output in real-time, flushing the buffer immediately
                    print(output.strip(), flush=True)
            # Continue once the process has finished
            if p.stdout:
                logging.debug(p.stdout)
            if p.stderr:
                logging.debug(p.stderr)
            if p.returncode == 0 and os.path.exists(out_srt):
                logging.info('Wrote subtitles: %s', out_srt)
                return True
            logging.warning('ffmpeg failed to extract subtitles for %s (exit %s); will attempt pgsrip if available', infile, p.returncode)
        except FileNotFoundError:
            logging.error('ffmpeg executable not found at %s', ffmpeg)

    # Fallback to pgsrip for PGS subtitles (or after ffmpeg failure)
    pgsrip_exists = shutil.which('pgsrip') or shutil.which('pgsrip.exe')
    if not pgsrip_exists:
        logging.error('pgsrip not found on PATH; cannot extract PGS subtitles for %s', infile)
        return False

    # Rip subtitles using pgsrip
    logging.info('Extracting English subtitles with pgsrip: %s', out_srt)
    try:
        media = Mkv(infile)
        options = Options(languages=[Language('eng')], overwrite=False, one_per_lang=True)
        pgsrip.rip(media, options)
        # pgsrip no longer accepts an explicit output filename in many
        # versions; it writes <input_basename>.en.srt next to the input
        # file. Check for both the requested out_srt and that default
        # filename, moving it if necessary.
        if os.path.exists(out_srt):
            logging.info('pgsrip wrote subtitles: %s', out_srt)
            return True

        # default pgsrip output name (in same dir as input)
        pgs_default_name = os.path.splitext(os.path.basename(infile))[0] + '.en.srt'
        pgs_default_path = os.path.join(os.path.dirname(infile), pgs_default_name)
        if os.path.exists(pgs_default_path):
            try:
                ensure_output_path(os.path.dirname(out_srt))
            except Exception:
                pass 
            try:
                shutil.move(pgs_default_path, out_srt)
                logging.info('Moved pgsrip output %s -> %s', pgs_default_path, out_srt)
                return True
            except Exception as e:
                logging.error('Failed to move pgsrip output %s to %s: %s', pgs_default_path, out_srt, e)
                # continue to try other commands if available
        else:
            logging.debug('pgsrip returned 0 but no output found at %s or %s', out_srt, pgs_default_path)
    except FileNotFoundError:
        logging.error('pgsrip executable not found at %s', pgsrip)
    except:
        logging.error('pgsrip failed to extract subtitles for %s', infile)
        return False

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
    cmd = [ffmpeg, '-i', mp4_path, '-map', '0', '-c', 'copy', '-metadata', f'title={metadata_title}', tmp, '-y']
    logging.info('Embedding title metadata: %s (from input: %s)', metadata_title, title)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        # Read the output line by line as it is generated
        while True:
            output = p.stdout.readline()
            # If the line is empty and the process has finished, break the loop
            if not output and p.poll() is not None:
                break
            if output:
                # Print the output in real-time, flushing the buffer immediately
                print(output.strip(), flush=True)
        # Continue once the process has finished
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
    parser.add_argument('--extract-subs', action='store_true', help='If present, extract English subtitles to a .default.srt alongside the MP4')
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
            # Dry-run: preview subtitle extraction if requested
            if args.extract_subs:
                srt_preview = os.path.splitext(outpath)[0] + '.default.srt'
                # attempt to detect subs (ffprobe) and report
                info = find_english_subtitle_info(mkv)
                if info is None:
                    logging.info('Dry-run: no English subtitles found in %s', mkv)
                else:
                    rel, codec = info
                    logging.info('Dry-run: would extract English subtitles to: %s (stream #%s codec=%s)', srt_preview, rel, codec)
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
            # extract English subtitles to .default.srt if requested
            if args.extract_subs:
                srt_path = os.path.splitext(outpath)[0] + '.default.en.srt'
                if dry_run:
                    # already logged preview above
                    pass
                else:
                    # ensure target dir exists
                    try:
                        ensure_output_path(os.path.dirname(srt_path))
                    except Exception:
                        pass
                    try:
                        extract_english_subtitles(mkv, srt_path, dry_run=False)
                    except Exception as e:
                        logging.warning('Failed to extract subtitles for %s: %s', mkv, e)

    logging.info('Summary: total=%d, succeeded=%d, failed=%d', total, successes, failures)
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
