#!/bin/bash
# Installs the Mac runner (every 30 min). Run from the repo folder:  bash mac/install.sh
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
/usr/bin/python3 -m pip install --user -q requests feedparser
mkdir -p ~/TenFourTapes/footage ~/TenFourTapes/queue ~/TenFourTapes/rendered ~/Library/LaunchAgents
sed "s#__REPO__#$REPO#g" "$REPO/mac/com.tenfourtapes.runner.plist" > ~/Library/LaunchAgents/com.tenfourtapes.runner.plist
launchctl unload ~/Library/LaunchAgents/com.tenfourtapes.runner.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.tenfourtapes.runner.plist
echo "Mac runner installed. Log: /tmp/tenfour-runner.log"
