#!/bin/bash
cd $HOME/Workspace/agent
python3 main.py "/daily-brief" > $HOME/Workspace/agent/daily_brief_run.log 2>&1
echo "EXIT_CODE:$?" >> $HOME/Workspace/agent/daily_brief_run.log
