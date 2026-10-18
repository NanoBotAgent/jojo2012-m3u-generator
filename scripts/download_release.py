import os
import json

urls = {
    '360p': 'https://pixeldrain.com/api/file/ApBTtMCs',
    '480p': 'https://pixeldrain.com/api/file/qmkbjjRz',
    '720p': 'https://pixeldrain.com/api/file/b5gcL8LM',
}

resolution = os.environ.get('JOJO_RESOLUTION', '720p')
url = urls[resolution]
filename = f'Alqanime_Jojo_BD_{resolution}.zip'

print(f'Downloading {url}')
import requests
r = requests.get(url, stream=True, timeout=7200)
r.raise_for_status()
with open(filename, 'wb') as f:
    for chunk in r.iter_content(chunk_size=8192):
        f.write(chunk)
size = os.path.getsize(filename)
print(f'Downloaded {filename} ({size} bytes)')
print(f'zip_path=/tmp/jojo/{filename}')