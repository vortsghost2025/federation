#!/bin/sh
# Federation Grafana Accessibility CSS Injector
# Injects <link> for custom.css into Grafana index.html template
# This runs BEFORE grafana-server starts

INDEX_HTML=/usr/share/grafana/public/views/index.html
CUSTOM_CSS=public/css/custom.css

# Need write access to grafana public dirs
mkdir -p /usr/share/grafana/public/css/
cp /etc/grafana/custom.css /usr/share/grafana/public/css/custom.css 2>/dev/null
echo "[accessibility] Copied custom.css to /usr/share/grafana/public/css/"

if [ -f "$INDEX_HTML" ]; then
  if grep -q "custom.css" "$INDEX_HTML" 2>/dev/null; then
    echo "[accessibility] custom.css link already present in index.html"
  else
    LINK_TAG='<link rel="stylesheet" href="'$CUSTOM_CSS'" />'
    sed -i "s|</head>| ${LINK_TAG}\n</head>|" "$INDEX_HTML"
    echo "[accessibility] Injected custom.css link into index.html"
  fi
else
  echo "[accessibility] WARNING: index.html not found at $INDEX_HTML"
fi

# Run the original Grafana entrypoint
exec /run.sh
