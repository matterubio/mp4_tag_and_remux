#!/usr/bin/env python3
"""Apply MusicBrainz release metadata to MP3 files in a directory.

Usage:
  python apply_mb_tags.py --discid <musicbrainz-discid> /path/to/mp3s

The script will:
- Lookup the release by disc id via musicbrainzngs (first release returned)
- Download the front cover from Cover Art Archive and save as `cover.png` in the directory
- For each MP3 in the directory, match by leading track number in filename
  (e.g. "01 - foo.mp3" -> track 1). Set ID3 tags (title, artist, album,
  track_num) and embed the cover. Rename files to "NN Track Title.mp3".
- If the album artist is "Various Artists", the filename will include the
  track artist appended like: "01 Track Title [Track Artist].mp3".

Requires: `musicbrainzngs`, `requests`, and `eyed3` installed for full
automation. The script will print helpful messages if packages are missing.
"""
from typing import Dict, List, Optional
import os
import sys
import re
import shutil


def sanitize_filename(name: str, max_len: int = 255) -> str:
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip().rstrip('.')
    if not name:
        name = 'output'
    if len(name) > max_len:
        name = name[:max_len]
    return name


def find_mp3_files(directory: str) -> List[str]:
    return sorted([os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith('.mp3')])


def fetch_release_by_discid(discid: str, index: int = 0) -> Optional[Dict]:
    try:
        import musicbrainzngs
    except Exception:
        print('musicbrainzngs not installed; please pip install musicbrainzngs', file=sys.stderr)
        return None

    musicbrainzngs.set_useragent('apply_mb_tags', '1.0', 'https://example.local/')
    try:
        res = musicbrainzngs.get_releases_by_discid(discid, includes=['artists', 'recordings'])
        rlist = res['disc'].get('release-list') or res.get('releases') or []
        if not rlist:
            print('No releases found for discid', discid, file=sys.stderr)
            return None
        release = rlist[min(index, len(rlist)-1)]

        # parse basic info and tracklist
        album = release.get('title')
        # artist-credit may be complex
        ac = release.get('artist-credit') or release.get('artist-credit-list') or []
        artist = None
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
            year = str(date).split('-')[0]

        # tracks -> medium-list -> track-list
        tracks = {}
        total_tracks = 0
        media = release.get('medium-list') or release.get('mediums') or []
        if media:
            try:
                tlist = media[0].get('track-list') or media[0].get('tracks') or []
                total_tracks = len(tlist)
                for t in tlist:
                    pos = t.get('position') or t.get('track-number') or t.get('number')
                    try:
                        pos_i = int(pos)
                    except Exception:
                        continue
                    title = t.get('recording', {}).get('title') or t.get('title')
                    tartist = None
                    ac2 = t.get('artist-credit') or t.get('artist-credit-list') or []
                    if ac2:
                        names2 = []
                        for it in ac2:
                            if isinstance(it, dict):
                                n = it.get('name') or it.get('artist', {}).get('name')
                                if n:
                                    names2.append(n)
                            elif isinstance(it, str):
                                names2.append(it)
                        tartist = ' & '.join(names2) if names2 else None
                    tracks[pos_i] = {'title': title, 'artist': tartist}
            except Exception:
                pass

        return {'artist': artist, 'album': album, 'year': year, 'tracks': tracks, 'total_tracks': total_tracks, 'id': release.get('id')}
    except Exception as e:
        print('MusicBrainz query failed:', e, file=sys.stderr)
        return None


def download_cover_art(release_id: str, outdir: str) -> Optional[str]:
    """Try to download front cover from Cover Art Archive and save as cover.png"""
    print("release id: " + release_id)
    try:
        import requests
    except Exception:
        print('requests not installed; please pip install requests to download cover art', file=sys.stderr)
        return None

    url = f'https://coverartarchive.org/release/{release_id}/front'
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.content:
            outpath = os.path.join(outdir, 'cover.png')
            with open(outpath, 'wb') as fh:
                fh.write(r.content)
            return outpath
        # try front-500
        url2 = f'https://coverartarchive.org/release/{release_id}/front-500'
        r2 = requests.get(url2, timeout=15)
        if r2.status_code == 200 and r2.content:
            outpath = os.path.join(outdir, 'cover.png')
            with open(outpath, 'wb') as fh:
                fh.write(r2.content)
            return outpath
    except Exception:
        pass
    return None


def tag_and_rename_mp3s(directory: str, release_info: Dict, cover_path: Optional[str], dry_run: bool = False) -> None:
    try:
        import eyed3
    except Exception:
        print('eyed3 not installed; please pip install eyed3 to tag files automatically', file=sys.stderr)
        return

    mp3s = find_mp3_files(directory)
    if not mp3s:
        print('No MP3 files found in', directory)
        return

    tracks = release_info.get('tracks', {})
    total = release_info.get('total_tracks') or (max(tracks.keys()) if tracks else None)
    album_artist = release_info.get('artist')
    album_title = release_info.get('album')

    for path in mp3s:
        fname = os.path.basename(path)
        m = re.match(r"^\s*(\d+)", fname)
        if not m:
            print('Skipping (no leading track number):', fname)
            continue
        tn = int(m.group(1))
        meta = tracks.get(tn)
        title = meta.get('title') if meta else None
        track_artist = meta.get('artist') if meta else None

        new_artist = track_artist if (album_artist and album_artist.lower() == 'various artists' and track_artist) else (album_artist or track_artist)

        # tagging
        print('Tagging track', tn, '->', fname)
        if not dry_run:
            audio = eyed3.load(path)
            if audio is None:
                print('Failed to load', path)
                continue
            if audio.tag is None:
                audio.initTag()
            if title:
                audio.tag.title = title
            if new_artist:
                audio.tag.artist = new_artist
            if album_title:
                audio.tag.album = album_title
            if release_info.get('year'):
                try:
                    audio.tag.recording_date = eyed3.core.Date(int(release_info.get('year')))
                except Exception:
                    pass
            try:
                if tn and total:
                    audio.tag.track_num = (tn, total)
                elif tn:
                    audio.tag.track_num = (tn,)
            except Exception:
                pass

            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, 'rb') as cf:
                        img = cf.read()
                    audio.tag.images.set(3, img, 'image/png')
                except Exception:
                    pass

            try:
                audio.tag.save(version=eyed3.id3.ID3_V2_3)
            except Exception:
                try:
                    audio.tag.save()
                except Exception:
                    pass

        # rename according to spec
        if title:
            track_title = sanitize_filename(title)
        else:
            # derive from original filename after number
            # Avoid regex character-range errors by placing '-' at the end of the class
            track_title = sanitize_filename(re.sub(r"^\s*\d+[\s._-]+", '', fname))

        width = len(str(total)) if total else 2
        tn_str = str(tn).zfill(width)
        if album_artist and album_artist.lower() == 'various artists' and track_artist:
            suffix = f" [{sanitize_filename(track_artist)}]"
        else:
            suffix = ''

        new_fname = f"{tn_str} {track_title}{suffix}.mp3"
        dest = os.path.join(directory, new_fname)
        if os.path.abspath(path) != os.path.abspath(dest):
            if os.path.exists(dest):
                # avoid overwrite
                base, ext = os.path.splitext(new_fname)
                i = 1
                while os.path.exists(os.path.join(directory, f"{base}-{i}{ext}")):
                    i += 1
                dest = os.path.join(directory, f"{base}-{i}{ext}")
            print('Renaming', fname, '->', os.path.basename(dest))
            if not dry_run:
                try:
                    os.replace(path, dest)
                except Exception:
                    try:
                        shutil.move(path, dest)
                    except Exception as e:
                        print('Failed to rename', path, '->', dest, e)


def main():
    import argparse
    p = argparse.ArgumentParser(description='Apply MusicBrainz metadata to MP3s in a directory by disc id')
    p.add_argument('--discid', required=True, help='MusicBrainz disc id (disc id returned by CD lookup)')
    p.add_argument('directory', help='Directory containing MP3 files')
    p.add_argument('--release-index', type=int, default=0, help='If multiple releases returned, which to use (default 0)')
    p.add_argument('--dry-run', action='store_true', help='Show actions without writing tags or renaming')
    args = p.parse_args()

    d = args.directory
    if not os.path.isdir(d):
        print('Not a directory:', d, file=sys.stderr)
        sys.exit(2)

    rel = fetch_release_by_discid(args.discid, index=args.release_index)
    if not rel:
        print('Failed to fetch release metadata for discid', args.discid, file=sys.stderr)
        sys.exit(1)

    cover = None
    if rel.get('id'):
        cover = download_cover_art(rel.get('id'), d)
        if cover:
            print('Saved cover art to', cover)
        else:
            print('No cover art found for release', rel.get('id'))

    tag_and_rename_mp3s(d, rel, cover, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
