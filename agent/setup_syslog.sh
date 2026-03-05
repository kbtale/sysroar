#!/bin/bash

# Syslog Forwarding Setup Script for Remote Agents
# Configures rsyslog to forward all logs to the Logstash instance.

LOGSTASH_HOST=${1:-"localhost"}
LOGSTASH_PORT=${2:-"5000"}

echo "Configuring rsyslog to forward to ${LOGSTASH_HOST}:${LOGSTASH_PORT}..."

# Create a new rsyslog configuration file
cat <<EOF | sudo tee /etc/rsyslog.d/99-sysroar.conf
*.* @${LOGSTASH_HOST}:${LOGSTASH_PORT}
EOF

# Restart rsyslog to apply changes
sudo systemctl restart rsyslog

echo "rsyslog has been configured and restarted."
echo "Bypassing SysRoar Core API for syslog forwarding - direct delivery to Logstash active."
