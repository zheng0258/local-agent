#!/bin/bash
source ~/.zshrc 2>/dev/null || source ~/.bash_profile 2>/dev/null
cd "$(dirname "$0")" || exit 1
python3 main.py "/daily-brief --force hatena reddit rss" >> daily_brief_run.log 2>&1
echo "EXIT_CODE:$?" >> daily_brief_run.log
