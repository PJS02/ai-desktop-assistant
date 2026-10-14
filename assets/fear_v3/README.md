# Fear v3

Created with the built-in image_gen tool, followed by user-authorized local background removal and frame extraction.

- Original `fear/` and `fear_v2/` assets are preserved.
- 36 transparent RGBA PNG frames, 273 x 402 pixels.
- 12 distinct poses, held for 3 frames each: 1.5 seconds at 24 fps.
- `preview.gif`: playback preview on a dark background.
- `quality_preview.png`: selected poses on light and dark backgrounds.
- `spritesheet.png`: extracted transparent source sheet.
- Runtime emotion mapping remains unchanged; this is a separately saved alternative.

Regenerate extraction: `.venv/Scripts/python.exe scripts/prepare_emotion_redesigns.py fear_v3 --preview-output assets/fear_v3/quality_preview.png`

## Generation prompt

Use case: identity-preserve.
Asset type: FEAR idle animation sprite sheet for a desktop mascot.
Input image 1 is the character identity and style reference. Input image 2 is the previous fear version to redesign.
Create ONE PNG sprite sheet, exactly 4 columns by 3 rows, 12 sequential full-body poses read left-to-right top-to-bottom, a seamless frightened idle loop. Equal cells on a square canvas, prefer 1536x1536.
Preserve exactly the blonde bob hairstyle, white cat-ear headphones with teal circular earcups, large brown eyes, black white teal futuristic jacket and skirt, mechanical gloves and boots, chibi proportions, crisp anime outlines and polished cel shading. Same character and costume in every cell.
A NEW fear expression clearly distinct from sadness or simple surprise: eyes wide with slightly smaller brown irises, worried inward-raised eyebrows, small trembling open mouth, shoulders raised, chin tucked, elbows pressed inward, both gloved fists held protectively close to upper chest, knees close and slightly bent. Cute anxious fearful expression, no tears, no extra floating symbols. Face remains frontal, body very slightly recoiled.
12 subtle sequential poses: small alternating shoulder tremble and slight hand quiver, brief tense blink near frames 6-7, then eyes reopen; first and last almost identical. Keep movement small, anchored feet, constant character size and camera. No walking, no dramatic pose changes.
EVERY cell has exactly one FULL character with generous transparent margin on all sides, no ears hair fingers or boots clipped, no overlapping cells. Uniform head scale and consistent foot baseline.
Background: real transparent alpha, not a painted checkerboard. No floor, no cast shadows outside character, no text, labels, frame numbers, borders, grid, watermark, additional props or characters.

