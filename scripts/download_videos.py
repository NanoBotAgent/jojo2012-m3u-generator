import os
import json
import requests
import sys

with open('video_urls.json') as f:
    urls = json.load(f)

os.makedirs('videos', exist_ok=True)
os.chdir('videos')

for i, url in enumerate(urls):
    ep = i + 1
    if not url or url == 'null':
        print(f'Skipping empty URL for episode {ep}')
        continue

    filename = f'Alqanime_Jojo_BD_{ep}_720p.mp4'
    if ep == 26:
        filename = 'Alqanime_Jojo_BD_26_END_720p.mp4'

    print(f'Downloading episode {ep} from {url}')
    print(f'Saving as {filename}')

    try:
        r = requests.get(url, stream=True, timeout=3600)
        r.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        size = os.path.getsize(filename)
        print(f'Downloaded {filename} ({size} bytes)')
    except Exception as e:
        print(f'::error::Failed to download episode {ep}: {e}')
        sys.exit(1)

print('Download complete')