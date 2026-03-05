#!/bin/bash

# Syslog Forwarding Setup Script for Remote Agents
# Configures rsyslog to forward all logs to the Logstash instance.

LOGSTASH_HOST=${1:-"localhost"}
LOGSTASH_PORT=${2:-"5000"}
SYSROAR_SERVER_ID=${3:-"unknown"}

if [ "$SYSROAR_SERVER_ID" == "unknown" ]; then
    echo "WARNING: No Server ID provided. Logs will not be tagged correctly. Usage: $0 <host> <port> <server_id>"
fi

echo "Configuring rsyslog to forward to ${LOGSTASH_HOST}:${LOGSTASH_PORT} with Server ID: ${SYSROAR_SERVER_ID}..."

# Create a new rsyslog configuration file
cat <<EOF | sudo tee /etc/rsyslog.d/99-sysroar.conf
# Tag all forwarded messages with the SysRoar server identifier
\$template SysRoarFormat,"<%pri%>%timestamp% sysroar-${SYSROAR_SERVER_ID} %syslogtag%%msg%\n"
*.* @${LOGSTASH_HOST}:${LOGSTASH_PORT};SysRoarFormat
EOF

# Restart rsyslog to apply changes
sudo systemctl restart rsyslog

echo "rsyslog has been configured and restarted."
echo "Bypassing SysRoar Core API for syslog forwarding - direct delivery to Logstash active."
