"""Extract the approved generated emotion sheets without touching original assets."""
from pathlib import Path
import argparse
import json

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
TARGET = (273, 402)


def extract(name):
    folder = ROOT / 'assets' / name
    sheet = Image.open(folder / 'spritesheet_draft.png').convert('RGB')
    rgb = np.asarray(sheet)
    values = rgb.astype(np.int16)
    neutral = ((values.max(2) - values.min(2) <= 26) & (values.min(2) >= 120)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(neutral, 8)
    # A connected checkerboard spans most of the canvas. White costume panels
    # are isolated by their dark outlines and are deliberately retained.
    background_labels = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 12000]
    background = np.isin(labels, background_labels)
    alpha = np.where(background, 0, 255).astype(np.uint8)
    rgba = np.dstack((rgb, alpha))
    rgba[background, :3] = 0
    clean = Image.fromarray(rgba)
    clean.save(folder / 'spritesheet.png')
    cells = []
    for index in range(12):
        col, row = index % 4, index // 4
        cell = clean.crop((round(col * sheet.width / 4), round(row * sheet.height / 3),
                           round((col + 1) * sheet.width / 4), round((row + 1) * sheet.height / 3)))
        # Keep the character, dropping stray slivers from adjacent sheet cells.
        a = np.asarray(cell.getchannel('A')).copy()
        n, lab, st, _ = cv2.connectedComponentsWithStats((a > 0).astype(np.uint8), 8)
        largest = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
        a[lab != largest] = 0
        cell.putalpha(Image.fromarray(a))
        bbox = cell.getbbox()
        if bbox is None:
            raise ValueError(f'Empty frame: {name}/{index}')
        cells.append(cell.crop(bbox))
    # One scale across the clip prevents changes in head size between poses.
    scale = min(263 / max(c.width for c in cells), 386 / max(c.height for c in cells))
    keyframes = []
    for index, cell in enumerate(cells):
        cell = cell.resize((round(cell.width * scale), round(cell.height * scale)), Image.Resampling.LANCZOS)
        frame = Image.new('RGBA', TARGET)
        frame.alpha_composite(cell, ((TARGET[0] - cell.width) // 2, 394 - cell.height))
        keyframes.append(frame)
        for hold in range(3):
            frame.save(folder / f'frame_{index * 3 + hold:03d}.png')
    # PNG playback has 36 frames at 24 fps, each generated pose held for 3 frames.
    preview_frames = []
    for frame in keyframes:
        canvas = Image.new('RGB', TARGET, '#28313e')
        canvas.paste(frame, mask=frame.getchannel('A'))
        preview_frames.append(canvas)
    preview_frames[0].save(folder / 'preview.gif', save_all=True, append_images=preview_frames[1:],
                           duration=125, loop=0, disposal=2)
    (folder / 'animation.json').write_text(json.dumps({
        'source': 'Built-in image_gen; background removal and slicing approved by user',
        'size': list(TARGET), 'fps': 24, 'frame_count': 36,
        'distinct_poses': 12, 'hold_frames_per_pose': 3, 'duration_seconds': 1.5,
        'runtime_enabled': False,
    }, indent=2), encoding='utf-8')
    return keyframes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', default=['sad_v3', 'angry_v2'])
    parser.add_argument('--preview-output', default='assets/emotion_redesign_preview.png')
    args = parser.parse_args()
    frames = {name: extract(name) for name in args.names}
    preview = Image.new('RGB', (4 * TARGET[0], len(frames) * (TARGET[1] + 30)))
    draw = ImageDraw.Draw(preview)
    for row, (name, poses) in enumerate(frames.items()):
        for col, index in enumerate((0, 6, 0, 6)):
            x, y = col * TARGET[0], row * (TARGET[1] + 30)
            draw.rectangle((x, y, x + TARGET[0], y + TARGET[1] + 30), fill='#ffffff' if col < 2 else '#202938')
            draw.text((x + 8, y + 8), f'{name} / pose {index}', fill='#445566' if col < 2 else '#ffffff')
            preview.paste(poses[index], (x, y + 30), poses[index].getchannel('A'))
    preview.save(ROOT / args.preview_output)
    print('Created 36 RGBA PNG frames per emotion, plus sheets and playback previews.')
