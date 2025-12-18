#!/usr/bin/env python3
"""Rip CD to MP3 using Exact Audio Copy (EAC) and tag files with ID3v2 (including cover art).

Usage examples:
    python mp3_rip_tag.py --outdir ripped --cover cover.jpg --ripper-cmd "\"C:\\Program Files\\ExactAudioCopy\\EAC.exe\" /SINGLE /OUTPUT={outdir}"
    python mp3_rip_tag.py --outdir ripped --artist "Artist" --album "Album" --ripper-cmd "C:\\tools\\eac.exe /OUTPUT={outdir}"

Prerequisites: Exact Audio Copy (EAC) when running on Windows, and either the Python
package `eyed3` (recommended) and `musicbrainzngs` for automatic tagging, or
the command-line tools `eyeD3`/`id3v2`. An MP3 encoder (`lame` or `ffmpeg`) is
required to convert WAVs to MP3.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import glob
import json
import shlex
from typing import Dict, Optional, Tuple


def sanitize_filename(name, max_len=255):
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip().rstrip(".")
    if not name:
        name = "output"
    if len(name) > max_len:
        name = name[:max_len]
    return name


def title_from_filename(fn):
    base = os.path.splitext(os.path.basename(fn))[0]
    m = re.match(r"^\s*\d+\s*[-._\s]+(.+)$", base)
    if m:
        return m.group(1).strip()
    return base


# Note: cdparanoia support removed; EAC is the default ripper.


def run_eac(outdir: str, eac_cmd: str, device: Optional[str], dry_run: bool) -> int:
    """Run Exact Audio Copy (EAC) using a user-provided command template.

    The `eac_cmd` is a command string which may contain the placeholders
    `{outdir}` and `{device}` which will be substituted. Example:
      "C:\\Program Files\\EAC\\EAC.exe /SINGLE /OUTPUT={outdir} /DRIVE={device}"

    Because EAC command-line automation varies by setup, the script requires
    the caller to supply a working command template when selecting the ripper.
    """
    if not eac_cmd:
        print("Error: EAC command template not provided (use --ripper-cmd).", file=sys.stderr)
        return 2

    # `device` may be supplied in the template via {device}; if not present, it's fine
    # caller should format the template including {device} if needed
    cmd_str = eac_cmd.format(outdir=outdir, device=(device or ""))
    cmd = shlex.split(cmd_str)
    print("Running EAC command:", cmd_str)
    if dry_run:
        return 0
    try:
        os.makedirs(outdir, exist_ok=True)
        proc = subprocess.run(cmd, cwd=outdir)
        return proc.returncode
    except FileNotFoundError:
        print("EAC executable not found or command failed.", file=sys.stderr)
        return 2


def find_wav_files(outdir):
    # Rippers write WAV files; accept common patterns including EAC outputs
    patterns = [os.path.join(outdir, '*.wav'), os.path.join(outdir, '*track*.wav'), os.path.join(outdir, '*.cdda.wav')]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    return sorted(files)


def encode_wavs_to_mp3(wav_files, outdir, encoder_preference=None, encoder_options=None, dry_run=False):
    """Encode WAV files to MP3 using available encoder: prefer `lame`, then `ffmpeg`.
    Returns list of produced mp3 file paths.
    """
    mp3_files = []
    # detect encoders
    has_lame = shutil.which('lame') is not None
    has_ffmpeg = shutil.which('ffmpeg') is not None
    encoder = None
    if encoder_preference == 'lame' and has_lame:
        encoder = 'lame'
    elif encoder_preference == 'ffmpeg' and has_ffmpeg:
        encoder = 'ffmpeg'
    elif has_lame:
        encoder = 'lame'
    elif has_ffmpeg:
        encoder = 'ffmpeg'
    else:
        print('No MP3 encoder found (lame or ffmpeg required).', file=sys.stderr)
        return mp3_files

    for wav in wav_files:
        base = os.path.splitext(os.path.basename(wav))[0]
        # normalize output name: preserve leading track number if present
        outname = f"{base}.mp3"
        outpath = os.path.join(outdir, outname)
        if dry_run:
            print(f"Would encode {wav} -> {outpath} with {encoder}")
            mp3_files.append(outpath)
            continue

        if encoder == 'lame':
            base_cmd = ['lame']
            if encoder_options:
                base_cmd += shlex.split(encoder_options)
            else:
                base_cmd += ['--preset', 'standard']
            cmd = base_cmd + [wav, outpath]
        else:
            base_cmd = ['ffmpeg', '-i', wav]
            if encoder_options:
                base_cmd += shlex.split(encoder_options)
            else:
                base_cmd += ['-codec:a', 'libmp3lame', '-q:a', '2']
            cmd = base_cmd + [outpath, '-y']

        print('Running:', ' '.join(cmd))
        proc = subprocess.run(cmd)
        if proc.returncode == 0 and os.path.exists(outpath):
            mp3_files.append(outpath)
    return mp3_files


def find_mp3_files(outdir):
    files = []
    for fn in os.listdir(outdir):
        if fn.lower().endswith('.mp3'):
            files.append(os.path.join(outdir, fn))
    return sorted(files)


def tag_with_eyed3(mp3_files, artist, album, year, genre, cover_file, disc=1, total=1, track_map=None, total_tracks=None):
    try:
        import eyed3
    except Exception as e:
        print("eyed3 Python package not available; cannot tag automatically.")
        print("Install via: pip install eyed3")
        return False

    for path in mp3_files:
        print("Tagging:", path)
        audio = eyed3.load(path)
        if audio is None:
            print("Failed to load:", path)
            continue
        if audio.tag is None:
            audio.initTag()

        # determine track number from filename
        m = re.match(r"^\s*(\d+)", os.path.basename(path))
        track_num = None
        if m:
            try:
                track_num = int(m.group(1))
            except Exception:
                track_num = None

        # prefer MusicBrainz-provided title if available, otherwise derive from filename
        title = None
        if track_map and track_num and track_map.get(track_num):
            title = track_map.get(track_num)
        if not title:
            title = title_from_filename(path)
        if title:
            audio.tag.title = title
        if artist:
            audio.tag.artist = artist
        if album:
            audio.tag.album = album
        if year:
            try:
                audio.tag.recording_date = eyed3.core.Date(int(year))
            except Exception:
                pass
        if genre:
            try:
                audio.tag.genre = genre
            except Exception:
                audio.tag.genre = None

        # Disc number (ID3v2) as (disc, total)
        try:
            audio.tag.disc_num = (int(disc) if disc else 1, int(total) if total else 1)
        except Exception:
            pass

        # set track number
        try:
            if track_num:
                tt = int(total_tracks) if total_tracks else (int(total) if total else None)
                if tt:
                    audio.tag.track_num = (track_num, tt)
                else:
                    audio.tag.track_num = (track_num,)
        except Exception:
            pass

        if cover_file and os.path.exists(cover_file):
            try:
                with open(cover_file, 'rb') as f:
                    img_data = f.read()
                audio.tag.images.set(3, img_data, 'image/jpeg')
            except Exception:
                try:
                    audio.tag.images.set(3, img_data, 'image/png')
                except Exception:
                    print("Failed to embed cover art for", path)

        try:
            audio.tag.save(version=eyed3.id3.ID3_V2_3)
        except Exception:
            try:
                audio.tag.save()
            except Exception as e:
                print("Failed to save tags for", path, e)
    return True


def get_discid() -> Optional[str]:
    """Return CD discid using `cd-discid` if available, otherwise None."""
    if not shutil.which("cd-discid"):
        return None
    try:
        proc = subprocess.run(["cd-discid"], capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        out = proc.stdout.strip()
        if not out:
            return None
        # cd-discid prints: <discid> <ntracks>
        parts = out.split()
        return parts[0]
    except Exception:
        return None


def fetch_musicbrainz_metadata(discid: str) -> Optional[Dict]:
    """Fetch release and track metadata from MusicBrainz by discid.
    Returns dict with keys: artist, album, year, tracks(dict), total_tracks
    or None on failure or if musicbrainzngs not installed.
    """
    try:
        import musicbrainzngs
    except Exception:
        return None

    try:
        musicbrainzngs.set_useragent("mp3_rip_tag", "1.0", "https://example.local/")
        res = musicbrainzngs.get_releases_by_discid(discid)
        # res may contain 'release-list'
        rlist = res.get('release-list') or res.get('releases') or []
        if not rlist:
            return None
        release = rlist[0]
        album = release.get('title')
        # artist-credit can be list of dicts
        artist = None
        ac = release.get('artist-credit') or release.get('artist-credit-list') or []
        if ac:
            names = []
            for item in ac:
                if isinstance(item, dict):
                    name = item.get('name') or item.get('artist', {}).get('name')
                    if name:
                        names.append(name)
                elif isinstance(item, str):
                    names.append(item)
            artist = ' & '.join(names) if names else None

        year = None
        date = release.get('date')
        if date:
            year = date.split('-')[0]

        tracks = {}
        total_tracks = 0
        media = release.get('medium-list') or release.get('mediums') or []
        if media:
            # take first medium
            try:
                tlist = media[0].get('track-list') or media[0].get('tracks') or []
                total_tracks = len(tlist)
                for t in tlist:
                    pos = t.get('position') or t.get('track-number') or t.get('number')
                    if isinstance(pos, str) and pos.isdigit():
                        pos = int(pos)
                    try:
                        pos_i = int(pos)
                    except Exception:
                        continue
                    title = t.get('recording', {}).get('title') or t.get('title')
                    if title:
                        tracks[pos_i] = title
            except Exception:
                pass

        return {'artist': artist, 'album': album, 'year': year, 'tracks': tracks, 'total_tracks': total_tracks}
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Rip CD to MP3 with abcde and tag resulting MP3s (ID3v2).")
    parser.add_argument("--outdir", default="ripped", help="Output directory for ripped MP3 files")
    parser.add_argument("--device", help="CD device (passed to ripper via -d where supported)")
    parser.add_argument("--ripper", choices=['eac'], default='eac',
                        help="Which ripper to use: 'eac' (default). Provide --ripper-cmd to run EAC.")
    parser.add_argument("--ripper-cmd", help="Command template to invoke the ripper (use {outdir} and {device} placeholders). Required for --ripper eac.")
    parser.add_argument("--artist", help="Album artist to set (overrides CDDB if provided)")
    parser.add_argument("--album", help="Album title to set (overrides CDDB if provided)")
    parser.add_argument("--year", help="Year to set in tags")
    parser.add_argument("--genre", help="Genre to set in tags")
    parser.add_argument("--cover", help="Path to cover image to embed in files")
    parser.add_argument("--disc", type=int, default=1, help="Disc number (default 1)")
    parser.add_argument("--total-discs", type=int, default=1, help="Total number of discs (default 1)")
    parser.add_argument("--encoder", choices=["lame", "ffmpeg"], help="Preferred encoder for WAV->MP3 (lame or ffmpeg)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without running ripper")
    parser.add_argument("--settings-file", default="eac_settings.json", help="Path to JSON settings file providing defaults (ripper_cmd,outdir,drive,encoder,encoder_options)")

    args = parser.parse_args()

    outdir = args.outdir

    # Load settings file if present and apply defaults where CLI didn't override
    settings = {}
    if args.settings_file and os.path.exists(args.settings_file):
        try:
            with open(args.settings_file, 'r', encoding='utf-8') as sf:
                settings = json.load(sf)
        except Exception as e:
            print(f"Failed to read settings file {args.settings_file}: {e}", file=sys.stderr)

    # Apply settings defaults (only when user didn't provide a non-default value)
    if outdir == 'ripped' and settings.get('outdir'):
        outdir = settings.get('outdir')
    if not args.ripper_cmd and settings.get('ripper_cmd'):
        args.ripper_cmd = settings.get('ripper_cmd')
    if not args.device and settings.get('drive'):
        args.device = settings.get('drive')
    # encoder defaults and options
    encoder_options = None
    if not args.encoder and settings.get('encoder'):
        args.encoder = settings.get('encoder')
    if settings.get('encoder_options'):
        encoder_options = settings.get('encoder_options')

    # Rip using EAC to WAVs (EAC is the default/only supported ripper)
    if args.ripper != 'eac':
        parser.error("Only the 'eac' ripper is supported in this script")
    if not args.ripper_cmd:
        parser.error("--ripper-cmd is required to run EAC; provide a working command template or put one in the settings file")
    ret = run_eac(outdir, args.ripper_cmd, args.device, args.dry_run)
    if ret != 0:
        print("ripper failed with exit code", ret, file=sys.stderr)
        sys.exit(ret)

    wavs = find_wav_files(outdir)
    if not wavs:
        print("No WAV files found in", outdir)
        if args.dry_run:
            print("Dry run; the configured ripper would produce WAVs in the output directory.")
        sys.exit(0)

    mp3s = encode_wavs_to_mp3(wavs, outdir, encoder_preference=args.encoder, encoder_options=encoder_options, dry_run=args.dry_run)
    if not mp3s:
        print('No MP3 files produced; aborting.', file=sys.stderr)
        sys.exit(1)
    if not mp3s:
        print("No MP3 files found in", outdir)
        if args.dry_run:
            print("Dry run; if abcde is available this will create MP3s in the output directory.")
        sys.exit(0)

    cover = args.cover
    if not cover:
        # common filenames to look for
        for cand in ("cover.jpg", "cover.png", "folder.jpg"):
            candp = os.path.join(outdir, cand)
            if os.path.exists(candp):
                cover = candp
                break

    # If key metadata not provided, try MusicBrainz via discid
    track_map = None
    total_tracks = None
    artist = args.artist
    album = args.album
    year = args.year
    genre = args.genre

    if not (artist and album and year):
        discid = get_discid()
        if discid:
            mb = fetch_musicbrainz_metadata(discid)
            if mb:
                if not artist and mb.get('artist'):
                    artist = mb.get('artist')
                if not album and mb.get('album'):
                    album = mb.get('album')
                if not year and mb.get('year'):
                    year = mb.get('year')
                if mb.get('tracks'):
                    track_map = mb.get('tracks')
                if mb.get('total_tracks'):
                    total_tracks = mb.get('total_tracks')

    success = tag_with_eyed3(mp3s, artist, album, year, genre, cover, args.disc, args.total_discs, track_map, total_tracks)
    if not success:
        print("Tagging via eyed3 not performed. You may install eyed3 or tag manually.")
        print("Example eyeD3 CLI: eyeD3 --add-image=cover.jpg:FRONT_COVER file.mp3")


if __name__ == "__main__":
    main()
