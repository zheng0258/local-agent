#!/bin/bash
source ~/.zshrc 2>/dev/null || source ~/.bash_profile 2>/dev/null
cd /Users/guangzhenglee/Workspace/agent
python3 main.py "/daily-brief --force hatena reddit rss" >> /Users/guangzhenglee/Workspace/agent/daily_brief_run.log 2>&1
echo "EXIT_CODE:$?" >> /Users/guangzhenglee/Workspace/agent/daily_brief_run.log
