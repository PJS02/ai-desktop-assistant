# Sad / Angry redesign drafts

Generated using the built-in image_gen tool. Original asset folders are unchanged.

- sad_v3/spritesheet_draft.png: 12 sad poses, 4 columns x 3 rows.
- angry_v2/spritesheet_draft.png: 12 angry poses, 4 columns x 3 rows.

Status: completed alternative animation assets. After explicit user approval, local image processing removed the generated checkerboard and extracted RGBA frames. Runtime mappings are unchanged; existing animations remain selected.

Each version contains `frame_000.png` through `frame_035.png` at 273 x 402 pixels, `preview.gif`, a transparent `spritesheet.png`, the original generated `spritesheet_draft.png`, and `animation.json`. There are 12 distinct generated poses held for 3 frames each, giving a 1.5-second loop at the application's 24 fps. These are held key poses, not 36 interpolated motion frames.

The generation tool supplied the artwork; `scripts/prepare_emotion_redesigns.py` removes the connected neutral background, discards neighboring-cell fragments, and aligns poses using a shared scale and foot baseline. White costume regions enclosed by outlines are preserved. `emotion_redesign_preview.png` shows selected frames against white and dark backgrounds for visual review.

## Sad prompt

Use case: identity-preserve.
Asset type: transparent PNG animation sprite sheet for a desktop mascot.
Input image 1 is the identity/style reference (neutral idle). Input image 2 is the old sad expression reference to redesign.
Create ONE sprite sheet with EXACTLY 4 columns and 3 rows: 12 full-body sprites of this SAME character, read left to right then top to bottom, a gentle seamless SAD idle animation. Uniform rectangular cells. Prefer canvas 1536x1536, every cell 384x512. TRUE transparent alpha background, no checkerboard, no floor or shadows outside character.
Preserve the blonde bob, white cat-ear headphones with teal circles, brown eyes, black white teal futuristic outfit, skirt, mechanical gloves and boots, chibi proportions and clean crisp anime linework. Exactly the same outfit and character across all cells. Front-facing, completely visible ears and feet, centered within each cell, uniform character size and constant foot baseline, ample empty margin separating cells. No overlaps.
Redesign sadness clearly: inner eyebrows raised, watery downcast brown eyes with small tears, small trembling downturned mouth, head slightly lowered, shoulders slumped, both gloved hands loosely clasped in front of waist. Cute vulnerable sadness, not exaggerated crying. Gentle breathing and very subtle head dip over frames 1-12, one slow blink in middle, tiny tear shimmer. Start and end poses nearly identical to loop. Keep small movement, no walking, fixed camera.
No text, no labels, no grid lines, no border, no accessories added, no background. All 12 cells must be populated with exactly one identical-character full-body sprite each.

## Angry prompt

Use case: identity-preserve. Asset: angry desktop mascot animation sprite sheet.
References: image 1 neutral character identity and outfit; image 2 old angry version for redesign.
Generate a transparent-background PNG sprite sheet with EXACTLY 4 columns by 3 rows, 12 full-body animation poses, left-to-right top-to-bottom. All cells equal size, no borders. Same full-body front-facing blonde bob chibi girl with white cat-ear teal headphones, brown eyes, white black teal sci-fi outfit, short skirt, mechanical gloves and boots. Preserve all identity and costume details and crisp anime outlines.
Redesign anger with brows angled down toward nose, clearly open annoyed brown eyes, a small angry pout, lightly flushed cheeks and clenched gloved fists beside waist with bent elbows; feet planted. Cute determined frustration. No crossed arms. Animation: very subtle exasperated breathing, shoulders rise then lower, fists tighten then relax very slightly, one brief blink in middle. Constant scale and feet baseline, no character rotation or camera motion, loop ends nearly as starts. All 12 sprites fully visible with empty margins around ears, hair, fists and feet. No cell touches or overlaps.
Background MUST be actually transparent alpha pixels, NOT a drawn gray-white checkerboard, NOT black, NOT white. No text, no frame numbers, no grid lines, no ground shadows, no watermarks. Prefer 1536x1536 output.
