import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from episode_titles import display_name


def main():
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    m3u_file = os.environ.get('M3U_FILE') or 'jojo2012-720p.m3u'

    with open(m3u_file, 'w') as fh:
        fh.write('#EXTM3U\n')
        for ep in range(1, 27):
            filename = f'Alqanime_Jojo_BD_{ep:02d}_720p.mp4'
            if ep == 26:
                filename = 'Alqanime_Jojo_BD_26_END_720p.mp4'

            raw_url = f'https://media.githubusercontent.com/media/{repo}/main/videos/{filename}'
            name = display_name(ep)

            fh.write(f'#EXTINF:-1 tvg-id="jojo2012-{ep:02d}" tvg-name="{name}",{name}\n')
            fh.write(f'{raw_url}\n')

    count = sum(1 for line in open(m3u_file) if line.startswith('https://'))
    print(f'Updated {m3u_file} with {count} video entries')
    return 0


if __name__ == '__main__':
    sys.exit(main())
