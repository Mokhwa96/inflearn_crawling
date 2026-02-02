# Inflearn Video Crawler

Downloads Inflearn lecture videos via HLS (AES-128) using Selenium Wire to capture the signed playlist and key requests.

## What Works
- AES-128 HLS streams (classic .m3u8 with #EXT-X-KEY:METHOD=AES-128).

## What Does NOT Work
- DRM/CMAF streams (e.g. drm/cmaf, skd://, METHOD=SAMPLE).
  These require a DRM license flow (Widevine, etc.) and are not supported here.
  The script detects DRM and stops immediately.

## Requirements
- Python 3
- Chrome + matching ChromeDriver
- selenium-wire
- pycryptodome (AES decrypt)
- Optional: fmpeg for remuxing to mp4

## Setup
1) Create .env in the project root:

`
INFLEARN_EMAIL=you@example.com
INFLEARN_PASSWORD=yourpassword
INFLEARN_LECTURE_URL=https://www.inflearn.com/courses/lecture?courseId=XXXXX&unitId=YYYYY
`

2) Install dependencies:
- pip install selenium-wire pycryptodome
- Install ChromeDriver (must match your Chrome version).

## Usage
`
python video_crawler.py
`

### Optional Environment Variables
- INFLEARN_UNIT_ID: Download only the specific unit id.
- INFLEARN_START_INDEX / INFLEARN_END_INDEX: Limit by index range.
- INFLEARN_MAX_UNITS: Limit number of units to process.
- INFLEARN_MAX_SEGMENTS: Limit number of segments (debug/testing).
- INFLEARN_FORCE=1: Re-download even if a file already exists.
- INFLEARN_REMUX=1: Remux .ts to .mp4 using fmpeg.

## Output
Files are saved under:
C:\src\inflearn\<lecture_title>\<index - title>.ts

If INFLEARN_REMUX=1 and fmpeg is installed, output is .mp4.

## Debugging
- M3U8 snapshots are saved in debug/.
- On key failure, a debug/key_fail_*.txt file is written with details.

## Notes
- If the first playlist is DRM/CMAF, the crawler stops and does not proceed to the next lecture.
- If key requests return 403, the stream is likely DRM or not compatible with this approach.
