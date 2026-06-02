import os
import urllib.request

# Define files to download
assets = {
    # Prism CSS
    "app/static/css/prism-tomorrow.min.css": "https://cdn.bootcdn.net/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css",
    "app/static/css/prism-line-numbers.min.css": "https://cdn.bootcdn.net/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.css",
    
    # Prism JS
    "app/static/js/prism-core.min.js": "https://cdn.bootcdn.net/ajax/libs/prism/1.29.0/components/prism-core.min.js",
    "app/static/js/prism-autoloader.min.js": "https://cdn.bootcdn.net/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js",
    "app/static/js/prism-line-numbers.min.js": "https://cdn.bootcdn.net/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.js",
    
    # FontAwesome CSS
    "app/static/css/font-awesome.min.css": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/css/all.min.css",
    
    # Marked JS (For Markdown Editor)
    "app/static/js/marked.min.js": "https://cdn.bootcdn.net/ajax/libs/marked/9.1.6/marked.min.js",
    
    # FontAwesome Webfonts
    "app/static/webfonts/fa-solid-900.woff2": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.woff2",
    "app/static/webfonts/fa-solid-900.ttf": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.ttf",
    "app/static/webfonts/fa-brands-400.woff2": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.woff2",
    "app/static/webfonts/fa-brands-400.ttf": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.ttf",
    "app/static/webfonts/fa-regular-400.woff2": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.woff2",
    "app/static/webfonts/fa-regular-400.ttf": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.ttf",
    "app/static/webfonts/fa-v4compat.woff2": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-v4compat.woff2",
    "app/static/webfonts/fa-v4compat.ttf": "https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/webfonts/fa-v4compat.ttf"
}

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

print("Starting asset localization...")
for local_path, url in assets.items():
    # Ensure directory exists
    dir_name = os.path.dirname(local_path)
    os.makedirs(dir_name, exist_ok=True)
    
    print(f"Downloading {url} -> {local_path}")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(local_path, 'wb') as out_file:
                out_file.write(response.read())
        print("Success")
    except Exception as e:
        print(f"FAILED to download {url}: {e}")

print("Localization completed!")
