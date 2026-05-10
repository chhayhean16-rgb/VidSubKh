#!/usr/bin/env python3
"""
VidSubKh — YouTube Downloader
Uses yt-dlp. Install: pip install yt-dlp
"""

import sys
import json
import os
import re
import subprocess

def get_info(url: str):
    """Fetch video metadata without downloading."""
    result = subprocess.run(
        ['yt-dlp', '--dump-json', '--no-playlist', url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'ERROR:{result.stderr}', file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    formats = []
    seen = set()
    for f in data.get('formats', []):
        h = f.get('height')
        if h and h not in seen:
            seen.add(h)
            formats.append({
                'height': h,
                'ext': f.get('ext', 'mp4'),
                'format_id': f.get('format_id'),
            })
    formats.sort(key=lambda x: x['height'], reverse=True)

    print(json.dumps({
        'title': data.get('title', 'Unknown'),
        'thumbnail': data.get('thumbnail', ''),
        'duration': data.get('duration', 0),
        'channel': data.get('uploader', ''),
        'formats': formats,
    }))


def download(url: str, quality: str, mode: str, output_dir: str, dl_id: str):
    """Download video/audio, printing PROGRESS: lines to stdout."""
    os.makedirs(output_dir, exist_ok=True)

    quality_map = {
        '4K': 'bestvideo[height<=2160]+bestaudio/best',
        '1080p': 'bestvideo[height<=1080]+bestaudio/best',
        '720p': 'bestvideo[height<=720]+bestaudio/best',
        '480p': 'bestvideo[height<=480]+bestaudio/best',
        '360p': 'bestvideo[height<=360]+bestaudio/best',
    }

    if mode == 'audio':
        fmt = 'bestaudio/best'
        post = ['-x', '--audio-format', 'mp3', '--audio-quality', '0']
    else:
        fmt = quality_map.get(quality, 'bestvideo+bestaudio/best')
        post = ['--merge-output-format', 'mp4']

    output_template = os.path.join(output_dir, '%(title).80s.%(ext)s')

    cmd = [
        'yt-dlp',
        '--no-playlist',
        '-f', fmt,
        '--newline',
        '-o', output_template,
        '--print', 'after_move:filepath',
        *post,
        url,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    file_path = None
    for line in proc.stdout:
        line = line.strip()
        # yt-dlp progress line: [download]  XX.X% of ...
        m = re.search(r'\[download\]\s+([\d.]+)%', line)
        if m:
            pct = float(m.group(1))
            # Extract speed and eta if present
            speed = re.search(r'at\s+([\d.]+\w+/s)', line)
            eta   = re.search(r'ETA\s+([\d:]+)', line)
            speed_str = speed.group(1) if speed else '-'
            eta_str   = eta.group(1)   if eta   else '-'
            print(f'PROGRESS:{pct:.1f}:{speed_str}:{eta_str}', flush=True)
        elif line and not line.startswith('['):
            # filepath printed after move
            if os.path.exists(line):
                file_path = line

    proc.wait()
    if proc.returncode == 0 and file_path:
        print(f'DONE:{file_path}', flush=True)
    else:
        err = proc.stderr.read()
        print(f'ERROR:{err}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'info':
        get_info(sys.argv[2])
    elif cmd == 'download':
        _, _, url, quality, mode, output_dir, dl_id = sys.argv
        download(url, quality, mode, output_dir, dl_id)
