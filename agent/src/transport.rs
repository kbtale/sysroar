use std::io::Write;
use std::time::Duration;
use flate2::write::GzEncoder;
use flate2::Compression;
use rand::Rng;
use reqwest::header::{CONTENT_ENCODING, CONTENT_TYPE, ETAG, IF_NONE_MATCH};
use reqwest::{Client, StatusCode};
use serde::Serialize;
use thiserror::Error;
use crate::collector::{HostInventory, MetricSample};
use crate::config::{AgentConfig, RemoteConfig};

#[derive(Debug, Error)]
pub enum TransportError {
    #[error("http transport error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("gzip compression error: {0}")]
    Io(#[from] std::io::Error),
    #[error("permanent client rejection: HTTP {0}")]
    Rejected(u16),
    #[error("retries exhausted after transient failure: HTTP {0}")]
    TransientExhausted(u16),
}

#[derive(Serialize)]
struct BatchEnvelope<'a> {
    samples: &'a [MetricSample],
}

pub fn gzip_json<T: Serialize>(value: &T) -> Result<Vec<u8>, TransportError> {
    let raw = serde_json::to_vec(value)?;
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(&raw)?;
    Ok(encoder.finish()?)
}

pub fn compute_jittered_backoff_ms(attempt: u32, base_ms: u64, max_ms: u64) -> u64 {
    let exp = base_ms.saturating_mul(1u64 << attempt.min(16));
    let ceiling = exp.min(max_ms).max(1);
    let mut rng = rand::thread_rng();
    rng.gen_range(0..=ceiling)
}

pub struct TransportClient {
    client: Client,
    config: AgentConfig,
    base_backoff_ms: u64,
    max_backoff_ms: u64,
}

impl TransportClient {
    pub fn new(config: AgentConfig) -> Result<Self, TransportError> {
        let client = Client::builder()
            .timeout(Duration::from_secs(15))
            .user_agent(format!("sysroar-agent/{}", env!("CARGO_PKG_VERSION")))
            .build()?;
        Ok(Self {
            client,
            config,
            base_backoff_ms: 500,
            max_backoff_ms: 30_000,
        })
    }

    pub fn with_backoff(mut self, base_ms: u64, max_ms: u64) -> Self {
        self.base_backoff_ms = base_ms;
        self.max_backoff_ms = max_ms;
        self
    }

    fn auth_header(&self) -> String {
        if self.config.api_token.starts_with("srk_") {
            format!("AgentKey {}", self.config.api_token)
        } else {
            format!("Token {}", self.config.api_token)
        }
    }

    pub async fn send_batch_with_retry(
        &self,
        samples: &[MetricSample],
        max_retries: u32,
    ) -> Result<(), TransportError> {
        if samples.is_empty() {
            return Ok(());
        }
        let body = gzip_json(&BatchEnvelope { samples })?;
        let url = self.config.batch_ingest_url();
        let auth_header = self.auth_header();

        let mut last_status = 0u16;
        for attempt in 0..=max_retries {
            let response = self
                .client
                .post(&url)
                .header("Authorization", &auth_header)
                .header(CONTENT_TYPE, "application/json")
                .header(CONTENT_ENCODING, "gzip")
                .body(body.clone())
                .send()
                .await;

            match response {
                Ok(resp) if resp.status().is_success() => return Ok(()),
                Ok(resp) => {
                    let code = resp.status();
                    last_status = code.as_u16();
                    if code.is_client_error() && code != StatusCode::TOO_MANY_REQUESTS {
                        return Err(TransportError::Rejected(last_status));
                    }
                    if attempt == max_retries {
                        return Err(TransportError::TransientExhausted(last_status));
                    }
                }
                Err(err) => {
                    if attempt == max_retries {
                        return Err(TransportError::Http(err));
                    }
                }
            }

            let delay_ms = compute_jittered_backoff_ms(attempt, self.base_backoff_ms, self.max_backoff_ms);
            tokio::time::sleep(Duration::from_millis(delay_ms)).await;
        }

        Err(TransportError::TransientExhausted(last_status))
    }

    pub async fn send_inventory(&self, inventory: &HostInventory) -> Result<(), TransportError> {
        let url = self.config.inventory_url();
        let auth_header = self.auth_header();
        let resp = self
            .client
            .post(&url)
            .header("Authorization", &auth_header)
            .json(inventory)
            .send()
            .await?;

        if resp.status().is_success() {
            return Ok(());
        }
        Err(TransportError::Rejected(resp.status().as_u16()))
    }

    pub async fn fetch_config(&self, etag: &mut Option<String>) -> Result<Option<RemoteConfig>, TransportError> {
        let url = self.config.config_url();
        let auth_header = self.auth_header();
        let mut req = self
            .client
            .get(&url)
            .header("Authorization", &auth_header)
            .header("X-Server-ID", &self.config.server_id);

        if let Some(current_etag) = etag.as_ref() {
            req = req.header(IF_NONE_MATCH, current_etag);
        }

        let resp = req.send().await?;
        if resp.status() == StatusCode::NOT_MODIFIED {
            return Ok(None);
        }
        if !resp.status().is_success() {
            return Err(TransportError::Rejected(resp.status().as_u16()));
        }

        if let Some(new_etag) = resp.headers().get(ETAG).and_then(|v| v.to_str().ok()) {
            *etag = Some(new_etag.to_string());
        }
        let remote: RemoteConfig = resp.json().await?;
        Ok(Some(remote))
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use chrono::Utc;
    use uuid::Uuid;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};
    use crate::collector::MetricDetails;
    use super::*;

    fn test_config(base_url: String) -> AgentConfig {
        AgentConfig {
            api_base_url: base_url,
            api_token: "test-token".to_string(),
            server_id: "00000000-0000-0000-0000-000000000001".to_string(),
            telemetry_cadence_secs: 30,
            config_poll_secs: 60,
            buffer_path: PathBuf::from("test.db"),
            max_buffer_rows: 1000,
            batch_size: 100,
            log_level: "INFO".to_string(),
            log_shipper_url: None,
            log_company_id: None,
            log_paths: Vec::new(),
        }
    }

    fn dummy_sample() -> MetricSample {
        MetricSample {
            server: "00000000-0000-0000-0000-000000000001".to_string(),
            sample_id: Uuid::now_v7(),
            timestamp: Utc::now(),
            cpu_usage: 25.0,
            ram_usage: 50.0,
            disk_io: 1.0,
            swap_usage: 5.0,
            disk_usage: 60.0,
            disk_read_bps: 100.0,
            disk_write_bps: 200.0,
            net_rx_bps: 300.0,
            net_tx_bps: 400.0,
            load_1m: 0.4,
            uptime_seconds: 1200,
            details: MetricDetails {
                per_core_cpu: vec![25.0],
                load_avg: [0.4, 0.3, 0.2],
                mounts: vec![],
                interfaces: vec![],
                ..MetricDetails::default()
            },
        }
    }

    #[tokio::test]
    async fn retries_transient_503_then_succeeds_with_gzip() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/telemetry/ingest/batch/"))
            .and(header("content-encoding", "gzip"))
            .and(header("authorization", "Token test-token"))
            .respond_with(ResponseTemplate::new(503))
            .up_to_n_times(1)
            .mount(&server)
            .await;

        Mock::given(method("POST"))
            .and(path("/api/telemetry/ingest/batch/"))
            .and(header("content-encoding", "gzip"))
            .respond_with(ResponseTemplate::new(202))
            .mount(&server)
            .await;

        let client = TransportClient::new(test_config(server.uri()))
            .unwrap()
            .with_backoff(5, 20);
        let res = client.send_batch_with_retry(&[dummy_sample()], 2).await;
        assert!(res.is_ok());
    }

    #[tokio::test]
    async fn does_not_retry_permanent_400() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/telemetry/ingest/batch/"))
            .respond_with(ResponseTemplate::new(400))
            .expect(1)
            .mount(&server)
            .await;

        let client = TransportClient::new(test_config(server.uri()))
            .unwrap()
            .with_backoff(5, 20);
        let err = client.send_batch_with_retry(&[dummy_sample()], 3).await.unwrap_err();
        assert!(matches!(err, TransportError::Rejected(400)));
    }

    #[tokio::test]
    async fn fetch_config_uses_etag_and_handles_304() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/api/telemetry/config/"))
            .and(header("x-server-id", "00000000-0000-0000-0000-000000000001"))
            .respond_with(
                ResponseTemplate::new(200)
                    .insert_header("ETag", "\"abc123\"")
                    .set_body_json(serde_json::json!({"telemetry_cadence": 15, "log_level": "DEBUG"})),
            )
            .up_to_n_times(1)
            .mount(&server)
            .await;

        Mock::given(method("GET"))
            .and(path("/api/telemetry/config/"))
            .and(header("if-none-match", "\"abc123\""))
            .respond_with(ResponseTemplate::new(304).insert_header("ETag", "\"abc123\""))
            .mount(&server)
            .await;

        let client = TransportClient::new(test_config(server.uri())).unwrap();
        let mut etag = None;
        let first = client.fetch_config(&mut etag).await.unwrap();
        assert_eq!(
            first,
            Some(RemoteConfig {
                telemetry_cadence: 15,
                log_level: "DEBUG".to_string()
            })
        );
        assert_eq!(etag.as_deref(), Some("\"abc123\""));

        let second = client.fetch_config(&mut etag).await.unwrap();
        assert_eq!(second, None);
    }

    #[test]
    fn backoff_is_bounded() {
        for attempt in 0..20 {
            let delay = compute_jittered_backoff_ms(attempt, 100, 1000);
            assert!(delay <= 1000);
        }
    }

    #[tokio::test]
    async fn agent_key_prefix_uses_agentkey_authorization_scheme() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/telemetry/ingest/batch/"))
            .and(header("authorization", "AgentKey srk_12345678.secretvalue"))
            .respond_with(ResponseTemplate::new(202))
            .expect(1)
            .mount(&server)
            .await;

        let mut cfg = test_config(server.uri());
        cfg.api_token = "srk_12345678.secretvalue".to_string();
        let client = TransportClient::new(cfg).unwrap();
        let res = client.send_batch_with_retry(&[dummy_sample()], 0).await;
        assert!(res.is_ok());
    }
}
