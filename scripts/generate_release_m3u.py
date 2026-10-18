import os

repo = os.environ.get('GITHUB_REPOSITORY', '')
run_number = os.environ.get('GITHUB_RUN_NUMBER', '1')
resolution = os.environ.get('JOJO_RESOLUTION', '720p')
release_tag = f'jojo2012-{resolution}-{run_number}'
base_url = f'https://github.com/{repo}/releases/download/{release_tag}/'

m3u_file = f'jojo2012-{resolution}.m3u'
asset_dir = os.environ.get('ASSET_DIR', 'release_assets')

files = sorted(os.listdir(asset_dir))

with open(m3u_file, 'w') as f:
    f.write('#EXTM3U\n')
    for i, filename in enumerate(files):
        ep = i + 1
        if ep <= 9:
            part = 'Phantom Blood'
            ep_display = f'{ep:02d}'
        else:
            part = 'Battle Tendency'
            ep_display = f'{ep - 9:02d}'

        url = base_url + filename
        f.write(f'#EXTINF:-1 tvg-id="jojo2012-{ep}" tvg-name="{part} - Episode {ep_display}",{part} - Episode {ep_display}\n')
        f.write(f'{url}\n')

print(f'Generated M3U with {len(files)} entries')
print(f'release_tag={release_tag}')
print(f'm3u_file={m3u_file}')