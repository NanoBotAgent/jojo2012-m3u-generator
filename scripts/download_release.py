import os
import sys

URLS = {
    '360p': 'https://pixeldrain.com/api/file/ApBTtMCs',
    '480p': 'https://pixeldrain.com/api/file/qmkbjjRz',
    '720p': 'https://pixeldrain.com/api/file/b5gcL8LM',
}


def emit(key, value):
    output_file = os.environ.get('GITHUB_OUTPUT')
    if output_file:
        with open(output_file, 'a', encoding='utf-8') as fh:
            fh.write(f'{key}={value}\n')
    print(f'{key}={value}')


def main():
    resolution = (os.environ.get('JOJO_RESOLUTION') or '720p').strip()
    if resolution not in URLS:
        print(f'::error::Unsupported resolution "{resolution}". Use one of: {", ".join(sorted(URLS))}')
        return 1

    url = URLS[resolution]
    filename = f'Alqanime_Jojo_BD_{resolution}.zip'
    work_dir = os.environ.get('JOJO_WORK_DIR', '/tmp/jojo')
    os.makedirs(work_dir, exist_ok=True)
    target = os.path.join(work_dir, filename)

    print(f'Downloading {url}')
    import requests
    response = requests.get(url, stream=True, timeout=7200)
    response.raise_for_status()
    with open(target, 'wb') as fh:
        for chunk in response.iter_content(chunk_size=8192):
            fh.write(chunk)
    size = os.path.getsize(target)
    print(f'Downloaded {filename} ({size} bytes)')

    emit('zip_path', target)
    emit('resolution', resolution)
    return 0


if __name__ == '__main__':
    sys.exit(main())
