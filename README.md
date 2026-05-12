# Apple Emoji Extractor

Export Apple Color Emoji PNGs from macOS with Docker.

This project is for the simple case: you have Docker on a Mac, you need Apple's emoji images as PNG files, and you do not want to install Python or leave temporary font/XML files in your project.

## Disclaimer

This project is for educational purposes only.

No Apple Color Emoji assets are included in this repository. The extractor works with the Apple Color Emoji font already present on your own macOS system.

All Apple Color Emoji assets and designs belong to Apple Inc. Apple is a registered trademark of Apple Inc. in the U.S. and other countries.

Using extracted emoji images or a font from a different operating system may have licensing implications; that responsibility is on you.

## Requirements

- macOS with `Apple Color Emoji.ttc`
- Docker Desktop for Mac

## Usage

Run one command from the project directory:

```bash
IMAGE_ID="$(docker build -q .)" && tar -cf - -C "/System/Library/Fonts" "Apple Color Emoji.ttc" -C "/System/Library/PrivateFrameworks/CoreEmoji.framework/Versions/A/Resources/en.lproj" "AppleName.strings" | docker run --rm -i -v "$PWD:/out" "$IMAGE_ID"; test -n "$IMAGE_ID" && docker rmi "$IMAGE_ID" >/dev/null
```

The command builds a temporary Docker image, streams the two macOS emoji metadata files into the container, exports the images, removes the container automatically, and removes the built image at the end.

## Output

The only project files created by a normal run are:

```text
images/
emoji_index.json
```

Images are saved by size:

```text
images/20x20/angry_face.png
images/40x40/angry_face.png
images/160x160/angry_face.png
```

Filenames are normalized to `snake_case`.

The extractor also writes `emoji_index.json`, which containing a map of text emojis to image files:

```json
{
  "angry_face": {
    "filename": "angry_face.png",
    "emoji": "😠",
    "name": "angry face",
    "codepoints": ["U+1F620"],
    "unicode_sequence": "1F620",
    "glyph_name": "u1F620",
    "files": {
      "20x20": "images/20x20/angry_face.png",
      "40x40": "images/40x40/angry_face.png",
      "160x160": "images/160x160/angry_face.png"
    }
  }
}
```

## License

GPL-3.0, following the upstream `emoji-extractor-plus` project.
