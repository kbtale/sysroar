#![forbid(unsafe_code)]

use std::time::Duration;
use sysroar_agent::buffer::DiskBuffer;
use sysroar_agent::collector::SystemCollector;
use sysroar_agent::config::{clamp_cadence, AgentConfig};
use sysroar_agent::transport::{TransportClient, TransportError};
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

async fn drain_buffer(
    buffer: &mut DiskBuffer,
    transport: &TransportClient,
    batch_size: usize,
) {
    loop {
        let entries = match buffer.peek_batch(batch_size) {
            Ok(v) if !v.is_empty() => v,
            Ok(_) => break,
            Err(err) => {
                error!(error = %err, "failed to read buffered samples");
                break;
            }
        };

        let ids: Vec<i64> = entries.iter().map(|(id, _)| *id).collect();
        let samples: Vec<_> = entries.into_iter().map(|(_, s)| s).collect();

        match transport.send_batch_with_retry(&samples, 3).await {
            Ok(()) => {
                if let Err(err) = buffer.ack_ids(&ids) {
                    error!(error = %err, "failed to acknowledge buffered samples");
                    break;
                }
                info!(count = samples.len(), "delivered telemetry batch");
                if samples.len() < batch_size {
                    break;
                }
            }
            Err(TransportError::Rejected(code)) => {
                warn!(status = code, count = samples.len(), "dropping permanently rejected batch");
                let _ = buffer.ack_ids(&ids);
                break;
            }
            Err(err) => {
                warn!(error = %err, buffered = ?buffer.len().ok(), "transient delivery failure; keeping samples buffered");
                break;
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt().json().with_env_filter(filter).init();

    let config = match AgentConfig::from_env() {
        Ok(c) => c,
        Err(err) => {
            error!(error = %err, "invalid agent configuration");
            std::process::exit(1);
        }
    };

    let mut buffer = match DiskBuffer::open(&config.buffer_path, config.max_buffer_rows) {
        Ok(b) => b,
        Err(err) => {
            error!(error = %err, "failed to open disk buffer");
            std::process::exit(1);
        }
    };

    let transport = match TransportClient::new(config.clone()) {
        Ok(t) => t,
        Err(err) => {
            error!(error = %err, "failed to initialize HTTP transport");
            std::process::exit(1);
        }
    };

    let mut collector = SystemCollector::new();
    let inventory = collector.collect_inventory(&config.server_id);
    if let Err(err) = transport.send_inventory(&inventory).await {
        warn!(error = %err, "startup inventory report failed; continuing");
    } else {
        info!(version = %inventory.agent_version, "reported host inventory");
    }

    let run_once = std::env::args().any(|arg| arg == "--once");
    if run_once {
        let sample = collector.collect_sample(&config.server_id);
        if let Err(err) = buffer.push(&sample) {
            error!(error = %err, "failed to buffer sample");
            std::process::exit(1);
        }
        drain_buffer(&mut buffer, &transport, config.batch_size).await;
        return;
    }

    let mut cadence_secs = config.telemetry_cadence_secs;
    let mut collect_interval = tokio::time::interval(Duration::from_secs(cadence_secs));
    let mut config_interval = tokio::time::interval(Duration::from_secs(config.config_poll_secs));
    let mut etag: Option<String> = None;

    info!(?config, "sysroar-agent started");

    loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                info!("shutdown signal received; exiting cleanly");
                break;
            }
            _ = collect_interval.tick() => {
                let sample = collector.collect_sample(&config.server_id);
                if let Err(err) = buffer.push(&sample) {
                    error!(error = %err, "failed to append sample to disk buffer");
                }
                drain_buffer(&mut buffer, &transport, config.batch_size).await;
            }
            _ = config_interval.tick() => {
                match transport.fetch_config(&mut etag).await {
                    Ok(Some(remote)) => {
                        let next_cadence = clamp_cadence(remote.telemetry_cadence);
                        if next_cadence != cadence_secs {
                            cadence_secs = next_cadence;
                            collect_interval = tokio::time::interval(Duration::from_secs(cadence_secs));
                            info!(cadence_secs, "updated telemetry cadence from remote config");
                        }
                    }
                    Ok(None) => {}
                    Err(err) => {
                        warn!(error = %err, "remote config refresh failed");
                    }
                }
            }
        }
    }
}
