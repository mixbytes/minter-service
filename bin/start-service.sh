#!/bin/bash

app=${1:-wsgi_app.py}

chmod -R 777 /app/data
if [[ "${WAIT:-yes}" = "yes" ]]; then
    ./bin/wait-for -q -t 60 ethereum_node:8545 -- sleep 5
fi

/usr/sbin/uwsgi \
    --http-socket :8000 \
    --master \
    --plugin python3 \
    --virtualenv /venv \
    --mount /minter-service=/app/bin/${app} --callable app \
    --uid uwsgi --gid uwsgi \
    --die-on-term \
    --processes 4
