#!/bin/sh
set -eu

REPO="${SYSROAR_RELEASE_REPO:-kbtale/sysroar}"
VERSION="${SYSROAR_AGENT_VERSION:-latest}"
API_URL="${SYSROAR_API_BASE_URL:-}"
ENROLL_TOKEN="${SYSROAR_ENROLLMENT_TOKEN:-}"
INSTALL_DIR="${SYSROAR_INSTALL_DIR:-/usr/local/bin}"
ENV_DIR="${SYSROAR_ENV_DIR:-/etc/sysroar-agent}"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "${OS}" in
  linux)
    case "${ARCH}" in
      x86_64|amd64) TARGET="x86_64-unknown-linux-musl" ;;
      aarch64|arm64) TARGET="aarch64-unknown-linux-musl" ;;
      *) echo "Unsupported Linux architecture: ${ARCH}" >&2; exit 1 ;;
    esac
    ;;
  darwin)
    case "${ARCH}" in
      x86_64) TARGET="x86_64-apple-darwin" ;;
      arm64|aarch64) TARGET="aarch64-apple-darwin" ;;
      *) echo "Unsupported macOS architecture: ${ARCH}" >&2; exit 1 ;;
    esac
    ;;
  *)
    echo "Unsupported OS: ${OS}" >&2
    exit 1
    ;;
esac

ARCHIVE="sysroar-agent-${TARGET}.tar.gz"
if [ "${VERSION}" = "latest" ]; then
  BASE_DOWNLOAD="https://github.com/${REPO}/releases/latest/download"
else
  BASE_DOWNLOAD="https://github.com/${REPO}/releases/download/${VERSION}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

curl -fsSL "${BASE_DOWNLOAD}/${ARCHIVE}" -o "${TMP_DIR}/${ARCHIVE}"
curl -fsSL "${BASE_DOWNLOAD}/${ARCHIVE}.sha256" -o "${TMP_DIR}/${ARCHIVE}.sha256"

EXPECTED_SHA="$(awk '{print $1}' "${TMP_DIR}/${ARCHIVE}.sha256")"
if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SHA="$(sha256sum "${TMP_DIR}/${ARCHIVE}" | awk '{print $1}')"
else
  ACTUAL_SHA="$(shasum -a 256 "${TMP_DIR}/${ARCHIVE}" | awk '{print $1}')"
fi

if [ "${EXPECTED_SHA}" != "${ACTUAL_SHA}" ]; then
  echo "Checksum verification failed for ${ARCHIVE}" >&2
  exit 1
fi

tar -xzf "${TMP_DIR}/${ARCHIVE}" -C "${TMP_DIR}"
install -m 0755 "${TMP_DIR}/sysroar-agent" "${INSTALL_DIR}/sysroar-agent"

if [ -n "${API_URL}" ] && [ -n "${ENROLL_TOKEN}" ]; then
  HOST_NAME="$(hostname)"
  ENROLL_JSON="$(curl -fsSL -X POST "${API_URL%/}/api/telemetry/enroll/" \
    -H "Content-Type: application/json" \
    -d "{\"enrollment_token\":\"${ENROLL_TOKEN}\",\"name\":\"${HOST_NAME}\",\"hostname\":\"${HOST_NAME}\"}")"
  SERVER_ID="$(printf '%s' "${ENROLL_JSON}" | sed -n 's/.*"server_id":"\([^"]*\)".*/\1/p')"
  AGENT_KEY="$(printf '%s' "${ENROLL_JSON}" | sed -n 's/.*"agent_key":"\([^"]*\)".*/\1/p')"
  if [ -z "${SERVER_ID}" ] || [ -z "${AGENT_KEY}" ]; then
    echo "Enrollment failed to return server_id and agent_key" >&2
    exit 1
  fi
  mkdir -p "${ENV_DIR}"
  umask 077
  cat > "${ENV_DIR}/agent.env" <<EOF
SYSROAR_API_BASE_URL=${API_URL%/}
SYSROAR_SERVER_ID=${SERVER_ID}
SYSROAR_AGENT_KEY=${AGENT_KEY}
EOF
  chmod 0600 "${ENV_DIR}/agent.env"

  if [ "${OS}" = "linux" ] && command -v systemctl >/dev/null 2>&1; then
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/agent/deploy/sysroar-agent.service" \
      -o /etc/systemd/system/sysroar-agent.service
    systemctl daemon-reload
    systemctl enable --now sysroar-agent
  elif [ "${OS}" = "darwin" ] && command -v launchctl >/dev/null 2>&1; then
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/agent/deploy/com.sysroar.agent.plist" \
      -o /Library/LaunchDaemons/com.sysroar.agent.plist
    launchctl unload /Library/LaunchDaemons/com.sysroar.agent.plist 2>/dev/null || true
    launchctl load -w /Library/LaunchDaemons/com.sysroar.agent.plist
  fi
fi

echo "SysRoar agent installed successfully at ${INSTALL_DIR}/sysroar-agent"
