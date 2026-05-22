#!/bin/bash
source ~/.zshrc 2>/dev/null || source ~/.bash_profile 2>/dev/null
cd $HOME/Workspace/agent
python3 main.py "/daily-brief" > $HOME/Workspace/agent/daily_brief_run.log 2>&1
echo "EXIT_CODE:$?" >> $HOME/Workspace/agent/daily_brief_run.log
