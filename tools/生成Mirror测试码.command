#!/bin/zsh
cd -- "${0:A:h}/.." || exit 1
PYTHONPATH=src .venv-mp021/bin/python -m makeup_refine.beta_codes
read -r '?按回车关闭…'
