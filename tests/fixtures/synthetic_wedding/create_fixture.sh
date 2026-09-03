#!/usr/bin/env bash
set -euo pipefail

fixture_dir="$(cd "$(dirname "$0")" && pwd)"
raw_dir="$fixture_dir/raw"
mkdir -p "$raw_dir"

for clip_index in $(seq -w 1 160); do
  ffmpeg -y -f lavfi -i "testsrc2=size=640x360:rate=25" -t 4 -an -c:v libx264 -pix_fmt yuv420p "$raw_dir/couple_${clip_index}.mp4"
done
ffmpeg -y -f lavfi -i "sine=frequency=880:sample_rate=44100:duration=0.04" -f lavfi -i "anullsrc=r=44100:cl=mono" -filter_complex "[0:a][1:a]adelay=500|500,amix=inputs=2,aloop=loop=299:size=23814" -t 150 "$fixture_dir/music.wav"

