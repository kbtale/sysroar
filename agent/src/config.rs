use std::env;
use std::fmt;
use std::path::PathBuf;
use serde::Deserialize;
use thiserror::Error;

pub const MIN_CADENCE_SECS: u64 = 5;
pub const MAX_CADENCE_SECS: u64 = 3600;
pub const DEFAULT_CADENCE_SECS: u64 = 30;
pub const DEFAULT_CONFIG_POLL_SECS: u64 = 60;
pub const DEFAULT_MAX_BUFFER_ROWS: usize = 50_000;
pub const DEFAULT_BATCH_SIZE: usize = 100;
pub const MAX_BATCH_SIZE: usize = 500;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("missing required environment variable: {0}")]
    MissingEnv(&'static str),
    #[error("invalid API base URL: {0}")]
    InvalidUrl(String),
}

#[derive(Clone)]
pub struct AgentConfig {
    pub api_base_url: String,
    pub api_token: String,
    pub server_id: String,
    pub telemetry_cadence_secs: u64,
    pub config_poll_secs: u64,
    pub buffer_path: PathBuf,
    pub max_buffer_rows: usize,
    pub batch_size: usize,
    pub log_level: String,
}

impl fmt::Debug for AgentConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("AgentConfig")
            .field("api_base_url", &self.api_base_url)
            .field("api_token", &"[REDACTED]")
            .field("server_id", &self.server_id)
            .field("telemetry_cadence_secs", &self.telemetry_cadence_secs)
            .field("config_poll_secs", &self.config_poll_secs)
            .field("buffer_path", &self.buffer_path)
            .field("max_buffer_rows", &self.max_buffer_rows)
            .field("batch_size", &self.batch_size)
            .field("log_level", &self.log_level)
            .finish()
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct RemoteConfig {
    pub telemetry_cadence: u64,
    pub log_level: String,
}

pub fn clamp_cadence(value: u64) -> u64 {
    value.clamp(MIN_CADENCE_SECS, MAX_CADENCE_SECS)
}

impl AgentConfig {
    pub fn from_env() -> Result<Self, ConfigError> {
        let api_base_url = env::var("SYSROAR_API_BASE_URL")
            .unwrap_or_else(|_| "http://localhost:8000".to_string())
            .trim_end_matches('/')
            .to_string();

        if !api_base_url.starts_with("http://") && !api_base_url.starts_with("https://") {
            return Err(ConfigError::InvalidUrl(api_base_url));
        }

        let api_token = env::var("SYSROAR_API_TOKEN")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .ok_or(ConfigError::MissingEnv("SYSROAR_API_TOKEN"))?;

        let server_id = env::var("SYSROAR_SERVER_ID")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .ok_or(ConfigError::MissingEnv("SYSROAR_SERVER_ID"))?;

        let telemetry_cadence_secs = env::var("SYSROAR_TELEMETRY_CADENCE")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .map(clamp_cadence)
            .unwrap_or(DEFAULT_CADENCE_SECS);

        let config_poll_secs = env::var("SYSROAR_CONFIG_POLL_SECS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .map(|v| v.clamp(10, 3600))
            .unwrap_or(DEFAULT_CONFIG_POLL_SECS);

        let buffer_path = env::var("SYSROAR_BUFFER_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("sysroar-buffer.db"));

        let max_buffer_rows = env::var("SYSROAR_MAX_BUFFER_ROWS")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .map(|v| v.clamp(100, 1_000_000))
            .unwrap_or(DEFAULT_MAX_BUFFER_ROWS);

        let batch_size = env::var("SYSROAR_BATCH_SIZE")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .map(|v| v.clamp(1, MAX_BATCH_SIZE))
            .unwrap_or(DEFAULT_BATCH_SIZE);

        let log_level = env::var("SYSROAR_LOG_LEVEL").unwrap_or_else(|_| "INFO".to_string());

        Ok(Self {
            api_base_url,
            api_token,
            server_id,
            telemetry_cadence_secs,
            config_poll_secs,
            buffer_path,
            max_buffer_rows,
            batch_size,
            log_level,
        })
    }

    pub fn batch_ingest_url(&self) -> String {
        format!("{}/api/telemetry/ingest/batch/", self.api_base_url)
    }

    pub fn inventory_url(&self) -> String {
        format!("{}/api/telemetry/inventory/", self.api_base_url)
    }

    pub fn config_url(&self) -> String {
        format!("{}/api/telemetry/config/", self.api_base_url)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamp_cadence_enforces_bounds() {
        assert_eq!(clamp_cadence(0), MIN_CADENCE_SECS);
        assert_eq!(clamp_cadence(30), 30);
        assert_eq!(clamp_cadence(99_999), MAX_CADENCE_SECS);
    }

    #[test]
    fn debug_redacts_api_token() {
        let cfg = AgentConfig {
            api_base_url: "https://monitor.example.com".to_string(),
            api_token: "super-secret-token-value".to_string(),
            server_id: "00000000-0000-0000-0000-000000000001".to_string(),
            telemetry_cadence_secs: 30,
            config_poll_secs: 60,
            buffer_path: PathBuf::from("buffer.db"),
            max_buffer_rows: 1000,
            batch_size: 100,
            log_level: "INFO".to_string(),
        };
        let formatted = format!("{cfg:?}");
        assert!(!formatted.contains("super-secret-token-value"));
        assert!(formatted.contains("[REDACTED]"));
    }
}
