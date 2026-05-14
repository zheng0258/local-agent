#!/bin/bash
cd /Users/guangzhenglee/Workspace/agent
python3 main.py "/daily-brief" > /Users/guangzhenglee/Workspace/agent/daily_brief_run.log 2>&1
echo "EXIT_CODE:$?" >> /Users/guangzhenglee/Workspace/agent/daily_brief_run.log
