#!/bin/bash
# A1 fixed run command: scripted crash-consistency sandbox, 1500 episodes/condition.
set -e
cd "$(dirname "$0")"
"$(dirname "$0")/../venv/bin/python" src/sandbox.py
