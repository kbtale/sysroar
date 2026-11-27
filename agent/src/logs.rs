#![forbid(unsafe_code)]

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::PathBuf;
use chrono::Utc;
use reqwest::Client;
use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ShippedLogLine {
    pub company_id: String,
    pub server_id: String,
    pub source: String,
    pub level: String,
    pub message: String,
    pub timestamp: String,
}

pub fn infer_log_level(line: &str) -> &'static str {
    let upper = line.to_ascii_uppercase();
    if upper.contains("CRITICAL") || upper.contains("FATAL") || upper.contains("PANIC") {
        "CRITICAL"
    } else if upper.contains("ERROR") || upper.contains("ERR ") || upper.contains("[ERR]") {
        "ERROR"
    } else if upper.contains("WARN") {
        "WARN"
    } else if upper.contains("DEBUG") {
        "DEBUG"
    } else {
        "INFO"
    }
}

pub struct LogTailer {
    company_id: String,
    server_id: String,
    paths: Vec<PathBuf>,
    offsets: HashMap<PathBuf, u64>,
}

impl LogTailer {
    pub fn new(company_id: String, server_id: String, paths: Vec<PathBuf>) -> Self {
        let mut offsets = HashMap::new();
        for p in &paths {
            if let Ok(meta) = std::fs::metadata(p) {
                offsets.insert(p.clone(), meta.len());
            } else {
                offsets.insert(p.clone(), 0);
            }
        }
        Self {
            company_id,
            server_id,
            paths,
            offsets,
        }
    }

    pub fn from_beginning(company_id: String, server_id: String, paths: Vec<PathBuf>) -> Self {
        let mut offsets = HashMap::new();
        for p in &paths {
            offsets.insert(p.clone(), 0);
        }
        Self {
            company_id,
            server_id,
            paths,
            offsets,
        }
    }

    pub fn poll(&mut self, max_lines: usize) -> Vec<ShippedLogLine> {
        let mut batch = Vec::new();
        for path in &self.paths {
            if batch.len() >= max_lines {
                break;
            }
            let Ok(mut file) = File::open(path) else {
                continue;
            };
            let Ok(meta) = file.metadata() else {
                continue;
            };
            let file_len = meta.len();
            let offset = self.offsets.entry(path.clone()).or_insert(0);
            if file_len < *offset {
                *offset = 0;
            }
            if file.seek(SeekFrom::Start(*offset)).is_err() {
                continue;
            }
            let source = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("file")
                .to_string();
            let mut reader = BufReader::new(file);
            let mut line = String::new();
            while batch.len() < max_lines {
                line.clear();
                match reader.read_line(&mut line) {
                    Ok(0) => break,
                    Ok(bytes_read) => {
                        *offset += bytes_read as u64;
                        let trimmed = line.trim_end_matches(&['\r', '\n'][..]);
                        if trimmed.is_empty() {
                            continue;
                        }
                        batch.push(ShippedLogLine {
                            company_id: self.company_id.clone(),
                            server_id: self.server_id.clone(),
                            source: source.clone(),
                            level: infer_log_level(trimmed).to_string(),
                            message: trimmed.to_string(),
                            timestamp: Utc::now().to_rfc3339(),
                        });
                    }
                    Err(_) => break,
                }
            }
        }
        batch
    }
}

pub async fn ship_log_batch(
    client: &Client,
    shipper_url: &str,
    entries: &[ShippedLogLine],
) -> Result<(), String> {
    if entries.is_empty() {
        return Ok(());
    }
    let resp = client
        .post(shipper_url)
        .json(entries)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if resp.status().is_success() {
        Ok(())
    } else {
        Err(format!("log shipper HTTP {}", resp.status().as_u16()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn tailer_reads_incremental_lines_and_handles_truncation() {
        let mut tmp = NamedTempFile::new().expect("temp file");
        writeln!(tmp, "2026-11-27 INFO service started").unwrap();
        writeln!(tmp, "2026-11-27 ERROR database timeout").unwrap();
        tmp.flush().unwrap();

        let path = tmp.path().to_path_buf();
        let mut tailer = LogTailer::from_beginning(
            "co-1".to_string(),
            "srv-1".to_string(),
            vec![path.clone()],
        );

        let first = tailer.poll(50);
        assert_eq!(first.len(), 2);
        assert_eq!(first[0].level, "INFO");
        assert_eq!(first[1].level, "ERROR");
        assert_eq!(first[1].company_id, "co-1");
        assert_eq!(first[1].server_id, "srv-1");

        assert!(tailer.poll(50).is_empty());

        writeln!(tmp, "2026-11-27 WARN disk nearly full").unwrap();
        tmp.flush().unwrap();
        let second = tailer.poll(50);
        assert_eq!(second.len(), 1);
        assert_eq!(second[0].level, "WARN");

        std::fs::write(&path, "2026-11-27 FATAL rotated crash\n").unwrap();
        let third = tailer.poll(50);
        assert_eq!(third.len(), 1);
        assert_eq!(third[0].level, "CRITICAL");
    }
}
