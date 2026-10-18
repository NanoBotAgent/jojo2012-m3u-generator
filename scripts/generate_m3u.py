import os

repo = os.environ.get('GITHUB_REPOSITORY', '')
m3u_file = 'jojo2012-720p.m3u'

with open(m3u_file, 'w') as f:
    f.write('#EXTM3U\n')
    for ep in range(1, 27):
        if ep <= 9:
            part = 'Phantom Blood'
            ep_display = f'{ep:02d}'
        else:
            part = 'Battle Tendency'
            ep_display = f'{ep - 9:02d}'

        filename = f'Alqanime_Jojo_BD_{ep}_720p.mp4'
        if ep == 26:
            filename = 'Alqanime_Jojo_BD_26_END_720p.mp4'

        raw_url = f'https://media.githubusercontent.com/media/{repo}/main/videos/{filename}'

        f.write(f'#EXTINF:-1 tvg-id="jojo2012-{ep}" tvg-name="{part} - Episode {ep_display}",{part} - Episode {ep_display}\n')
        f.write(f'{raw_url}\n')

count = sum(1 for _ in open(m3u_file) if _.startswith('https://'))
print(f'Updated M3U with {count} video entries')