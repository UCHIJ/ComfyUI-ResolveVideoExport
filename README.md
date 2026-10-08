# ComfyUI Export for DaVinci Resolve

Export ComfyUI videos in formats **DaVinci Resolve (including the free version) can actually import**: **DNxHR** and **ProRes** in a `.mov` container, with audio.

DaVinci Resolve **Free** has limited support for the H.264/H.265 `.mp4` files ComfyUI normally saves:

- **Linux:** no H.264/H.265 decoding at all, and no AAC audio.
- **Windows:** partial support. It depends on the codec profile and on what your operating system provides (for example, H.265/HEVC often won't import without an OS-level decoder, and 10-bit and some other profiles are Studio-only).

The result is clips that fail to import or import with missing video or audio. These nodes avoid the problem: generate in ComfyUI, then drop a Resolve-friendly `.mov` straight into your timeline, with no manual conversion step.

*Exact codec support varies by Resolve version and platform. See Blackmagic's documentation for the current list.*



## Features

- **Two nodes:** one for ComfyUI `VIDEO` objects, one for raw `IMAGE` batches (with optional `AUDIO`)
- **7 presets:** DNxHR (HQ, HQX 10-bit, SQ, LB) and ProRes 422 (HQ, Standard, LT)
- **Audio included** as uncompressed PCM
- **Correct colors:** converted to BT.709 limited range and tagged, so Resolve reads them properly
- **True 10-bit path** for HQX and ProRes (16-bit frames are fed to the encoder)
- **Saves to any subfolder** of your ComfyUI `output` directory
- Progress bar, cancel support, and automatic cleanup of partial files if something fails
- Returns the saved file path, so you can preview or chain it into other nodes

## Requirements

- A recent version of **ComfyUI**. That's it.

No separate FFmpeg install is needed. The nodes encode with **PyAV** (`av`), which ComfyUI already uses for its own video nodes and which includes its own FFmpeg libraries.

## Installation

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/UCHIJ/ComfyUI-ResolveVideoExport.git
```

Restart ComfyUI.


## Usage

Both nodes are in the **Export** category. Double-click the canvas and search for "DaVinci Resolve".

### Exporting an existing video

Use **Export Video for DaVinci Resolve (from VIDEO)**.

1. Add a **Load Video** node and choose your clip
2. Connect its `VIDEO` output to the exporter's `video` input
3. Pick a `codec_preset`
4. Run the workflow
5. Find your file in `ComfyUI/output/video/` (or the folder you set in `filename_prefix`)

<img width="1906" height="861" alt="Screenshot from 2026-10-08 09-50-52" src="https://github.com/user-attachments/assets/ab8fd1e0-2641-4e1c-b490-c91bbaf049e9" />

An example workflow is included: [`workflow-example-export-for-resolve.json`](workflow-example-export-for-resolve.json). Drag it onto the ComfyUI canvas, select a video in the Load Video node, and run it. A **Preview Any** node on the output shows you the saved file path.

### Exporting generated images (with optional audio)

Use **Export Video for DaVinci Resolve (from IMAGES)**.

1. Connect your `IMAGE` batch (for example from a VAE Decode node)
2. Set `fps` to match your generation (decimals like `23.976` work)
3. Optionally connect an `AUDIO` source
4. Pick a `codec_preset` and run

<img width="1906" height="861" alt="Screenshot from 2026-10-08 09-54-28" src="https://github.com/user-attachments/assets/a2c4643d-128a-441b-8dee-d90199a60334" />


### Importing into DaVinci Resolve

Drag the `.mov` file from your output folder into Resolve's **Media Pool**, or use **File → Import → Media**.

## Node reference

### Export Video for DaVinci Resolve (from VIDEO)

| Input | Type | Description |
|---|---|---|
| `video` | VIDEO | Video from Load Video or any node that outputs a `VIDEO` |
| `filename_prefix` | STRING | Output name and optional subfolder. Default `video/Resolve_Export` |
| `codec_preset` | CHOICE | See presets below |

Frame rate and audio are taken from the video automatically.

### Export Video for DaVinci Resolve (from IMAGES)

| Input | Type | Description |
|---|---|---|
| `images` | IMAGE | Frame batch |
| `fps` | FLOAT | Frame rate (1-120, decimals allowed) |
| `filename_prefix` | STRING | Output name and optional subfolder. Default `video/Resolve_Export` |
| `codec_preset` | CHOICE | See presets below |
| `audio` | AUDIO *(optional)* | Audio track to include |

### Output (both nodes)

| Output | Type | Description |
|---|---|---|
| `filepath` | STRING | Full path of the saved `.mov` file |

## Presets

| Preset | Codec | Bit depth | Best for |
|---|---|---|---|
| DNxHR HQ | DNxHR | 8-bit | Good default for most work |
| DNxHR HQX | DNxHR | 10-bit | Highest quality DNxHR, for grading |
| DNxHR SQ | DNxHR | 8-bit | Smaller files, still good quality |
| DNxHR LB | DNxHR | 8-bit | Smallest files, for proxies/offline edits |
| ProRes 422 HQ | ProRes | 10-bit | Highest quality ProRes |
| ProRes 422 Standard | ProRes | 10-bit | Balanced quality and size |
| ProRes 422 LT | ProRes | 10-bit | Smaller ProRes files |

**Which should I pick?** If you aren't sure, start with **DNxHR HQ**. It's widely supported, including on Linux. If your platform's Resolve doesn't import ProRes, use DNxHR.

Both formats are intermediate/editing codecs. **Expect files many times larger than the equivalent `.mp4`.**

## Choosing the output folder

The `filename_prefix` can include a subfolder, and ComfyUI creates it for you:

| `filename_prefix` | Saved to |
|---|---|
| `video/Resolve_Export` | `output/video/Resolve_Export_00001_.mov` |
| `Resolve_Export` | `output/Resolve_Export_00001_.mov` |
| `resolve/project_x/shot01` | `output/resolve/project_x/shot01_00001_.mov` |

Files are numbered automatically, so nothing is overwritten. Output must stay inside ComfyUI's `output` directory.

## Notes and limitations

- **Odd dimensions:** DNxHR/ProRes need even width and height. Odd-sized frames are padded by 1 pixel with black.
- **DNxHR minimum size:** DNxHR requires frames of at least **256x120**. For smaller frames, upscale first or use a ProRes preset.
- **Alpha is dropped.** Output is RGB-derived 4:2:2 video without transparency.
- **Audio** is written as 16-bit PCM and trimmed to the video length. If the audio is shorter than the video, the video isn't cut short.
- **Memory:** frames are converted and encoded one at a time, but the input batch itself still has to fit in memory as usual for ComfyUI.

## Troubleshooting

**"PyAV ('av') is not installed"**
Update ComfyUI to a recent version. If you can't, install it manually in ComfyUI's Python environment with `pip install av`, then restart ComfyUI.

**"Encoding failed"**
The message includes the underlying error. Please open an issue and include it, along with your preset and the size of your frames.

**"DNxHR requires frames of at least 256x120"**
Your images are too small for DNxHR. Upscale them or switch to a ProRes preset.

**The file won't play in my browser or ComfyUI preview**
That's expected. ProRes and DNxHR aren't browser formats. The file is meant for Resolve and other editors. Open it in Resolve, VLC, or mpv to check it.

**Resolve imports the video but there's no audio**
Use the `from VIDEO` node with a video that has audio, or connect an `AUDIO` input to the `from IMAGES` node.

## Contributing

Issues and pull requests are welcome.
