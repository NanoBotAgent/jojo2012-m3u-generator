import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from episode_titles import display_name


def emit(key, value):
    output_file = os.environ.get('GITHUB_OUTPUT')
    if output_file:
        with open(output_file, 'a', encoding='utf-8') as fh:
            fh.write(f'{key}={value}\n')
    print(f'{key}={value}')


def episode_from_filename(filename):
    match = re.search(r'_(\d{2})(?:_END)?_', filename)
    if match:
        return int(match.group(1))
    return None


def main():
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    run_number = os.environ.get('GITHUB_RUN_NUMBER', '1')
    resolution = (os.environ.get('JOJO_RESOLUTION') or '720p').strip()
    release_tag = f'jojo2012-{resolution}-{run_number}'
    base_url = f'https://github.com/{repo}/releases/download/{release_tag}/'

    m3u_file = os.environ.get('M3U_FILE') or f'jojo2012-{resolution}-release.m3u'
    asset_dir = os.environ.get('ASSET_DIR', 'release_assets')

    if not os.path.isdir(asset_dir):
        print(f'::error::Asset directory not found: {asset_dir}')
        return 1

    files = sorted(f for f in os.listdir(asset_dir) if not f.startswith('.'))
    if not files:
        print(f'::error::No assets found in {asset_dir}')
        return 1

    with open(m3u_file, 'w') as fh:
        fh.write('#EXTM3U\n')
        for index, filename in enumerate(files):
            ep = episode_from_filename(filename)
            if ep is None:
                ep = index + 1
                print(f'::warning::Could not parse episode number from {filename}, using {ep}')
            name = display_name(ep) if 1 <= ep <= 26 else f'Episode {ep:02d}'
            url = base_url + filename
            fh.write(f'#EXTINF:-1 tvg-id="jojo2012-{ep:02d}" tvg-name="{name}",{name}\n')
            fh.write(f'{url}\n')

    print(f'Generated M3U with {len(files)} entries')
    emit('release_tag', release_tag)
    emit('m3u_file', m3u_file)
    emit('episode_count', str(len(files)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
