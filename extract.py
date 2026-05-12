#!/usr/bin/env python3

from argparse import ArgumentParser
from bplist.bplist import BPListReader
from fontTools.misc.xmlWriter import XMLWriter
from fontTools.ttLib import TTFont
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps
from xml.etree import ElementTree

import codecs
import json
import os
import re
import sys
import tarfile
import tempfile


DEFAULT_TTC_FILE = '/System/Library/Fonts/Apple Color Emoji.ttc'
DEFAULT_NAMES_FILE = '/System/Library/PrivateFrameworks/CoreEmoji.framework/Versions/A/Resources/en.lproj/AppleName.strings'


class ExtractionError(Exception):
    pass


def safe_extract_tar_from_stdin(destination):
    destination = Path(destination).resolve()

    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|*') as tar:
        for member in tar:
            member_path = (destination / member.name).resolve()

            if not str(member_path).startswith(str(destination) + os.sep):
                raise ExtractionError(f'Unsafe path in tar stream: {member.name}')

            tar.extract(member, path=destination)


def find_required_file(root, filename):
    root = Path(root)
    matches = list(root.rglob(filename))

    if not matches:
        raise ExtractionError(f'Could not find {filename} in input files')

    return str(matches[0])


def write_sbix_to_file(ttc_file, output_directory, font_number=1):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    xml_filename = Path(ttc_file).name + '.xml'
    out_filename = output_directory / xml_filename

    print(f'extracting sbix chunk to temporary file {out_filename}')

    with open(out_filename, 'wb') as fx:
        mx = XMLWriter(fx)
        mx.begintag('root')

        font = TTFont(ttc_file, fontNumber=font_number)
        sbix = font['sbix']
        sbix.toXML(xmlWriter=mx, ttFont=font)

        mx.endtag('root')
        mx.close()

    return str(out_filename)


def get_parsed_strings(names_file):
    with open(names_file, 'rb') as fp:
        reader = BPListReader(fp.read())
        parsed = reader.parse()

    new_parsed = parsed.copy()

    for key in parsed:
        graphical_key = key.replace('\ufe0f', '').replace('\u20E3', '').replace('\u200d', '')
        value = parsed[key]

        if isinstance(value, bytes):
            value = value.decode()

        new_parsed[graphical_key] = value

    return new_parsed


def extract_strikes_from_file(filename):
    sbix_table = ElementTree.parse(filename)
    return sbix_table.findall('strike')


def escaped_string_from_string(string):
    hex_code = string.replace('u', '')
    number = int(hex_code, 16)
    return '\\U{:0>8X}'.format(number)


def normalize_filename_base(name):
    name = name.strip().lower()
    name = name.replace('/', ' ')
    name = name.replace('&', ' and ')
    name = re.sub(r"['’]", '', name)
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')

    return name or 'unnamed'


def codepoints_for_text(text):
    return [f'U+{ord(char):04X}' for char in text]


def unicode_sequence_for_text(text):
    return '-'.join(f'{ord(char):04X}' for char in text)


def unique_key_for_metadata(emoji_index, base_key, emoji, codepoints):
    if base_key not in emoji_index:
        return base_key

    if emoji_index[base_key]['emoji'] == emoji:
        return base_key

    suffix = '_'.join(cp.replace('U+', '').lower() for cp in codepoints)
    candidate = f'{base_key}_{suffix}'
    counter = 2

    while candidate in emoji_index and emoji_index[candidate]['emoji'] != emoji:
        candidate = f'{base_key}_{suffix}_{counter}'
        counter += 1

    return candidate


def extract_pngs_from_sbix_xml_file(sbix_xml_file, names_file, output_dir):
    names = get_parsed_strings(names_file)
    strikes = extract_strikes_from_file(sbix_xml_file)
    emoji_index = {}

    output_dir = Path(output_dir)
    images_root = output_dir / 'images'

    modifier_matcher = re.compile(r'\.(?P<skin_tone>[0-5]{0,1})?\.?(?P<gender>[MWBG]{0,4})?')
    code_matcher = re.compile(r'([A-F0-9]{4,8})')

    def image_from_hexdata(hexdata):
        if hexdata is None or not hexdata.text:
            return None

        filtered_text = re.sub(r'[\n\s]', '', hexdata.text)
        image_data = bytearray.fromhex(filtered_text)

        image = Image.open(BytesIO(image_data))
        image.load()
        return image

    def metadata_for_glyph(glyph):
        glyph_name = glyph.attrib.get('name', '')
        modifiers = modifier_matcher.search(glyph_name)
        codes = code_matcher.findall(glyph_name)

        if not codes:
            return None

        emoji = ''.join(chr(int(code, 16)) for code in codes)
        skin_tone = None
        gender = None

        if modifiers is not None:
            mod_dict = modifiers.groupdict()
            skin_tone = mod_dict.get('skin_tone')
            gender = mod_dict.get('gender')

        skin_tone_map = {
            '1': '\U0001F3FB',
            '2': '\U0001F3FC',
            '3': '\U0001F3FD',
            '4': '\U0001F3FE',
            '5': '\U0001F3FF',
        }

        if skin_tone in skin_tone_map:
            emoji += skin_tone_map[skin_tone]

        if gender == 'M':
            emoji += '\u200d\u2642\ufe0f'
        elif gender == 'W':
            emoji += '\u200d\u2640\ufe0f'

        lookup_string = ''

        for code in codes:
            if 'fe0f' in code.lower() or '20e3' in code.lower():
                continue

            lookup_string += escaped_string_from_string(code)

        try:
            decoded_lookup = codecs.decode(lookup_string, 'unicode-escape')
        except Exception:
            decoded_lookup = emoji

        if gender == 'W':
            decoded_lookup += '\u2640'
        elif gender == 'M':
            decoded_lookup += '\u2642'

        try:
            name = names[decoded_lookup].replace('/', ' ')
        except KeyError:
            name = glyph_name
            print(f'No name found for {decoded_lookup} ({lookup_string}). Saved as {name}.png')

        if gender and gender not in ('M', 'W'):
            name += f' {gender.lower()}'

        if skin_tone:
            name += f' {skin_tone}'

        key = normalize_filename_base(name)
        codepoints = codepoints_for_text(emoji)

        return {
            'key': key,
            'filename': f'{key}.png',
            'emoji': emoji,
            'name': name,
            'codepoints': codepoints,
            'unicode_sequence': unicode_sequence_for_text(emoji),
            'glyph_name': glyph_name,
        }

    for strike in strikes:
        glyphs_by_name = {
            glyph.attrib.get('name'): glyph
            for glyph in strike
            if glyph.attrib.get('name')
        }

        image_cache = {}

        def resolve_image(glyph, seen=None):
            if glyph is None:
                return None

            if seen is None:
                seen = set()

            glyph_name = glyph.attrib.get('name')

            if not glyph_name or glyph_name in seen:
                return None

            if glyph_name in image_cache:
                return image_cache[glyph_name].copy()

            seen.add(glyph_name)
            hexdata = glyph.find('hexdata')
            ref = glyph.find('ref')
            image = None

            if hexdata is not None:
                try:
                    image = image_from_hexdata(hexdata)
                except Exception as exc:
                    print(f'skipping {glyph_name}: cannot open embedded data ({exc})')
                    return None

            elif ref is not None:
                ref_name = ref.attrib.get('glyphname')
                ref_glyph = glyphs_by_name.get(ref_name)
                image = resolve_image(ref_glyph, seen)

                if image is not None and (glyph.attrib.get('graphicType') or '').strip() == 'flip':
                    image = ImageOps.mirror(image)

            if image is not None:
                image_cache[glyph_name] = image.copy()

            return image

        for glyph in strike:
            image = resolve_image(glyph)

            if image is None:
                continue

            meta = metadata_for_glyph(glyph)

            if meta is None:
                print(f"skipping {glyph.attrib.get('name')}: cannot build metadata")
                continue

            key = unique_key_for_metadata(emoji_index, meta['key'], meta['emoji'], meta['codepoints'])

            if key != meta['key']:
                meta['key'] = key
                meta['filename'] = f'{key}.png'

            size_key = f'{image.size[0]}x{image.size[1]}'
            image_dir = images_root / size_key
            image_dir.mkdir(parents=True, exist_ok=True)

            image_path = image_dir / meta['filename']
            image.save(image_path)

            if key not in emoji_index:
                emoji_index[key] = {
                    'filename': meta['filename'],
                    'emoji': meta['emoji'],
                    'name': meta['name'],
                    'codepoints': meta['codepoints'],
                    'unicode_sequence': meta['unicode_sequence'],
                    'glyph_name': meta['glyph_name'],
                    'files': {},
                }

            emoji_index[key]['files'][size_key] = str(Path('images') / size_key / meta['filename'])
            print(f'saved {image_path}')

    index_path = output_dir / 'emoji_index.json'
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(index_path, 'w', encoding='utf-8') as fp:
        json.dump(emoji_index, fp, ensure_ascii=False, indent=2, sort_keys=True)

    print(f'saved {index_path}')


def main():
    parser = ArgumentParser(description='Extract Apple Color Emoji PNGs and generate emoji_index.json')
    parser.add_argument('-f', '--ttc-file', default=DEFAULT_TTC_FILE, help='Path to Apple Color Emoji.ttc')
    parser.add_argument('-n', '--names-file', default=DEFAULT_NAMES_FILE, help='Path to AppleName.strings')
    parser.add_argument('-o', '--output-dir', default='.', help='Directory where images/ and emoji_index.json will be written')
    parser.add_argument('--font-number', type=int, default=1, help='Font number inside the .ttc file')
    parser.add_argument('--input-tar', choices=['-'], help='Read Apple Color Emoji.ttc and AppleName.strings from a tar stream on stdin')

    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix='apple-emoji-extractor-') as temp_dir:
        temp_dir_path = Path(temp_dir)

        if args.input_tar == '-':
            input_dir = temp_dir_path / 'input'
            input_dir.mkdir(parents=True, exist_ok=True)
            safe_extract_tar_from_stdin(input_dir)
            args.ttc_file = find_required_file(input_dir, 'Apple Color Emoji.ttc')
            args.names_file = find_required_file(input_dir, 'AppleName.strings')

        sbix_xml_file = write_sbix_to_file(args.ttc_file, temp_dir_path, font_number=args.font_number)
        extract_pngs_from_sbix_xml_file(sbix_xml_file, args.names_file, args.output_dir)


if __name__ == '__main__':
    main()
