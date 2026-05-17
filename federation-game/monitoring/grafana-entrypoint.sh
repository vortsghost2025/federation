#!/bin/sh
# Federation Grafana Accessibility CSS Injector
# Injects <link> for custom.css into Grafana's index.html template
# This runs BEFORE grafana-server starts

INDEX_HTML="/usr/share/grafana/public/views/index.html"
CUSTOM_CSS="public/css/custom.css"
LINK_TAG='<link rel="stylesheet" href="'"${CUSTOM_CSS}"'" />'

if [ -f "$INDEX_HTML" ]; then
    # Check if already injected (idempotent)
    if grep -q "custom.css" "$INDEX_HTML" 2>/dev/null; then
        echo "[accessibility] custom.css link already present in index.html"
    else
        # Inject before the closing </head> tag
        sed -i "s|</head>|  ${LINK_TAG}\n</head>|" "$INDEX_HTML"
        echo "[accessibility] Injected custom.css link into index.html"
    fi
else
    echo "[accessibility] WARNING: index.html not found at $INDEX_HTML"
fi

# Also copy the custom.css into the correct location inside the container
mkdir -p /usr/share/grafana/public/css/
if [ -f /etc/grafana/custom.css ]; then
    cp /etc/grafana/custom.css /usr/share/grafana/public/css/custom.css
    echo "[accessibility] Copied custom.css to /usr/share/grafana/public/css/"
else
    echo "[accessibility] WARNING: /etc/grafana/custom.css not found"
fi

# Start Grafana normally
exec grafana-server --homepath=/usr/share/grafana \
    --config=/etc/grafana/grafana.ini \
    cfg:default.paths.data=/var/lib/grafana \
    cfg:default.paths.logs=/var/log/grafana \
    cfg:default.paths.plugins=/var/lib/grafana/plugins \
    cfg:default.paths.provisioning=/etc/grafana/provisioning
