use std::path::Path;
use chrono::Utc;
use rusqlite::{params, Connection};
use thiserror::Error;
use crate::collector::MetricSample;

#[derive(Debug, Error)]
pub enum BufferError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),
}

pub struct DiskBuffer {
    conn: Connection,
    max_rows: usize,
}

impl DiskBuffer {
    pub fn open<P: AsRef<Path>>(path: P, max_rows: usize) -> Result<Self, BufferError> {
        if let Some(parent) = path.as_ref().parent() {
            if !parent.as_os_str().is_empty() {
                let _ = std::fs::create_dir_all(parent);
            }
        }
        let conn = Connection::open(path)?;
        conn.execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA synchronous = NORMAL;
             CREATE TABLE IF NOT EXISTS sample_buffer (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 payload TEXT NOT NULL,
                 created_at INTEGER NOT NULL
             );",
        )?;
        Ok(Self {
            conn,
            max_rows: max_rows.max(1),
        })
    }

    pub fn push(&mut self, sample: &MetricSample) -> Result<i64, BufferError> {
        let payload = serde_json::to_string(sample)?;
        let now = Utc::now().timestamp();
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO sample_buffer (payload, created_at) VALUES (?1, ?2)",
            params![payload, now],
        )?;
        let row_id = tx.last_insert_rowid();
        let count: i64 = tx.query_row("SELECT COUNT(*) FROM sample_buffer", [], |r| r.get(0))?;
        let max_i64 = self.max_rows as i64;
        if count > max_i64 {
            let overflow = count - max_i64;
            tx.execute(
                "DELETE FROM sample_buffer WHERE id IN (
                    SELECT id FROM sample_buffer ORDER BY id ASC LIMIT ?1
                )",
                params![overflow],
            )?;
        }
        tx.commit()?;
        Ok(row_id)
    }

    pub fn peek_batch(&self, limit: usize) -> Result<Vec<(i64, MetricSample)>, BufferError> {
        let mut stmt = self
            .conn
            .prepare("SELECT id, payload FROM sample_buffer ORDER BY id ASC LIMIT ?1")?;
        let rows = stmt.query_map(params![limit as i64], |row| {
            let id: i64 = row.get(0)?;
            let payload: String = row.get(1)?;
            Ok((id, payload))
        })?;

        let mut items = Vec::new();
        for row in rows {
            let (id, payload) = row?;
            let sample: MetricSample = serde_json::from_str(&payload)?;
            items.push((id, sample));
        }
        Ok(items)
    }

    pub fn ack_ids(&mut self, ids: &[i64]) -> Result<usize, BufferError> {
        if ids.is_empty() {
            return Ok(0);
        }
        let tx = self.conn.transaction()?;
        let mut deleted = 0usize;
        {
            let mut stmt = tx.prepare("DELETE FROM sample_buffer WHERE id = ?1")?;
            for id in ids {
                deleted += stmt.execute(params![id])?;
            }
        }
        tx.commit()?;
        Ok(deleted)
    }

    pub fn len(&self) -> Result<usize, BufferError> {
        let count: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM sample_buffer", [], |r| r.get(0))?;
        Ok(count.max(0) as usize)
    }

    pub fn is_empty(&self) -> Result<bool, BufferError> {
        Ok(self.len()? == 0)
    }
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;
    use uuid::Uuid;
    use crate::collector::MetricDetails;
    use super::*;

    fn sample_with_cpu(cpu: f64) -> MetricSample {
        MetricSample {
            server: "00000000-0000-0000-0000-000000000001".to_string(),
            sample_id: Uuid::now_v7(),
            timestamp: Utc::now(),
            cpu_usage: cpu,
            ram_usage: 50.0,
            disk_io: 0.0,
            swap_usage: 0.0,
            disk_usage: 40.0,
            disk_read_bps: 0.0,
            disk_write_bps: 0.0,
            net_rx_bps: 0.0,
            net_tx_bps: 0.0,
            load_1m: 0.5,
            uptime_seconds: 100,
            details: MetricDetails {
                per_core_cpu: vec![cpu],
                load_avg: [0.5, 0.4, 0.3],
                mounts: vec![],
                interfaces: vec![],
                ..MetricDetails::default()
            },
        }
    }

    #[test]
    fn disk_buffer_preserves_fifo_order_and_evicts_oldest_when_bounded() {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("buffer.db");
        let mut buf = DiskBuffer::open(&db_path, 3).unwrap();

        for cpu in [10.0, 20.0, 30.0, 40.0, 50.0] {
            buf.push(&sample_with_cpu(cpu)).unwrap();
        }

        assert_eq!(buf.len().unwrap(), 3);
        let batch = buf.peek_batch(10).unwrap();
        let cpus: Vec<f64> = batch.iter().map(|(_, s)| s.cpu_usage).collect();
        assert_eq!(cpus, vec![30.0, 40.0, 50.0]);

        let ids: Vec<i64> = batch.iter().take(2).map(|(id, _)| *id).collect();
        buf.ack_ids(&ids).unwrap();
        assert_eq!(buf.len().unwrap(), 1);
        let remaining = buf.peek_batch(10).unwrap();
        assert_eq!(remaining[0].1.cpu_usage, 50.0);
    }

    #[test]
    fn disk_buffer_persists_across_reopen() {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("persist.db");
        {
            let mut buf = DiskBuffer::open(&db_path, 100).unwrap();
            buf.push(&sample_with_cpu(77.5)).unwrap();
        }
        let buf = DiskBuffer::open(&db_path, 100).unwrap();
        assert_eq!(buf.len().unwrap(), 1);
        assert_eq!(buf.peek_batch(1).unwrap()[0].1.cpu_usage, 77.5);
    }
}
