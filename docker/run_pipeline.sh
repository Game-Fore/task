#!/usr/bin/env sh
set -eu

python -m etl migrate
python -m etl load
python -m etl mart
python -m ml train
python -m ml score
