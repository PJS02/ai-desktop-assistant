# URL Bridge

## What it does
- Sends foreground video playback and PDF tab status to the running desktop app.
- Sends the active tab URL to the standalone classifier when its local receiver is running.

## Install (Chrome or Edge)
1. Open the Extensions page.
2. Enable Developer Mode.
3. Load unpacked and select this folder.
4. Keep the extension enabled.

## Local HTTP Receiver
The desktop app receives activity on port 8766. Open a supported video site or a PDF tab with a `.pdf` URL. After reloading an installed extension, reload any open video tabs.

The standalone classifier receives the active tab URL on port 8765.
