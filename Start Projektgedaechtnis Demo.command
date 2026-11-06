#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_git_common=$(git -C "$task_root" rev-parse --git-common-dir)
case "$task_git_common" in
  /*) ;;
  *) task_git_common="$task_root/$task_git_common" ;;
esac
task_main_root=$(CDPATH= cd -- "$task_git_common/.." && pwd)
task_python=${THREADDESK_PYTHON:-"$task_main_root/.venv/bin/python"}
if [ ! -x "$task_python" ]; then
  task_python=python3
fi
export PYTHONPATH="$task_root/src"
exec "$task_python" "$task_root/scripts/demo_project_memory.py" --serve --open
