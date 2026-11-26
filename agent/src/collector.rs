use std::collections::BTreeMap;
use std::time::Instant;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sysinfo::{Disks, Networks, System};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostInventory {
    pub server: String,
    pub hostname: Option<String>,
    pub os_info: Option<String>,
    pub kernel: Option<String>,
    pub cpu_model: Option<String>,
    pub cpu_cores: Option<usize>,
    pub total_ram_bytes: u64,
    pub ip_address: Option<String>,
    pub agent_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MountMetric {
    pub mount: String,
    pub used_percent: f64,
    pub total_bytes: u64,
    pub available_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InterfaceMetric {
    pub name: String,
    pub rx_bps: f64,
    pub tx_bps: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MetricDetails {
    pub per_core_cpu: Vec<f64>,
    pub load_avg: [f64; 3],
    pub mounts: Vec<MountMetric>,
    pub interfaces: Vec<InterfaceMetric>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MetricSample {
    pub server: String,
    pub sample_id: Uuid,
    pub timestamp: DateTime<Utc>,
    pub cpu_usage: f64,
    pub ram_usage: f64,
    pub disk_io: f64,
    pub swap_usage: f64,
    pub disk_usage: f64,
    pub disk_read_bps: f64,
    pub disk_write_bps: f64,
    pub net_rx_bps: f64,
    pub net_tx_bps: f64,
    pub load_1m: f64,
    pub uptime_seconds: u64,
    pub details: MetricDetails,
}

pub struct SystemCollector {
    sys: System,
    disks: Disks,
    networks: Networks,
    last_collected_at: Instant,
    last_disk_bytes: Option<(u64, u64)>,
}

impl SystemCollector {
    pub fn new() -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();
        let disks = Disks::new_with_refreshed_list();
        let networks = Networks::new_with_refreshed_list();
        let last_disk_bytes = read_total_disk_io_bytes();
        Self {
            sys,
            disks,
            networks,
            last_collected_at: Instant::now(),
            last_disk_bytes,
        }
    }

    pub fn collect_inventory(&mut self, server_id: &str) -> HostInventory {
        self.sys.refresh_cpu_all();
        self.sys.refresh_memory();
        self.networks.refresh(true);

        let hostname = System::host_name();
        let os_info = System::long_os_version().or_else(System::name);
        let kernel = System::kernel_version();
        let cpu_model = self
            .sys
            .cpus()
            .first()
            .map(|c| c.brand().trim().to_string())
            .filter(|s| !s.is_empty());
        let cpu_cores = Some(self.sys.cpus().len().max(1));
        let total_ram_bytes = self.sys.total_memory();
        let ip_address = self.detect_primary_ip();

        HostInventory {
            server: server_id.to_string(),
            hostname,
            os_info,
            kernel,
            cpu_model,
            cpu_cores,
            total_ram_bytes,
            ip_address,
            agent_version: env!("CARGO_PKG_VERSION").to_string(),
        }
    }

    fn detect_primary_ip(&self) -> Option<String> {
        for (_name, data) in &self.networks {
            for ip_net in data.ip_networks() {
                if !ip_net.addr.is_loopback() && !ip_net.addr.is_unspecified() {
                    return Some(ip_net.addr.to_string());
                }
            }
        }
        None
    }

    pub fn collect_sample(&mut self, server_id: &str) -> MetricSample {
        let now = Instant::now();
        let elapsed_secs = now.duration_since(self.last_collected_at).as_secs_f64().max(0.1);
        self.last_collected_at = now;

        self.sys.refresh_cpu_all();
        self.sys.refresh_memory();
        self.disks.refresh(true);
        self.networks.refresh(true);

        let cpu_usage = clamp_percent(f64::from(self.sys.global_cpu_usage()));
        let per_core_cpu: Vec<f64> = self
            .sys
            .cpus()
            .iter()
            .map(|c| round2(clamp_percent(f64::from(c.cpu_usage()))))
            .collect();

        let total_mem = self.sys.total_memory();
        let used_mem = self.sys.used_memory();
        let ram_usage = if total_mem > 0 {
            clamp_percent((used_mem as f64 / total_mem as f64) * 100.0)
        } else {
            0.0
        };

        let total_swap = self.sys.total_swap();
        let used_swap = self.sys.used_swap();
        let swap_usage = if total_swap > 0 {
            clamp_percent((used_swap as f64 / total_swap as f64) * 100.0)
        } else {
            0.0
        };

        let load_avg_raw = read_load_average();
        let load_1m = load_avg_raw[0].max(0.0);

        let mut mount_map: BTreeMap<String, MountMetric> = BTreeMap::new();
        let mut max_disk_percent = 0.0_f64;
        for disk in &self.disks {
            let total = disk.total_space();
            if total == 0 {
                continue;
            }
            let available = disk.available_space().min(total);
            let used = total.saturating_sub(available);
            let pct = clamp_percent((used as f64 / total as f64) * 100.0);
            if pct > max_disk_percent {
                max_disk_percent = pct;
            }
            let mount = disk.mount_point().to_string_lossy().to_string();
            mount_map.insert(
                mount.clone(),
                MountMetric {
                    mount,
                    used_percent: round2(pct),
                    total_bytes: total,
                    available_bytes: available,
                },
            );
        }

        let current_disk_bytes = read_total_disk_io_bytes();
        let (disk_read_bps, disk_write_bps, disk_io_mb) = match (self.last_disk_bytes, current_disk_bytes) {
            (Some((prev_r, prev_w)), Some((cur_r, cur_w))) => {
                let dr = cur_r.saturating_sub(prev_r) as f64;
                let dw = cur_w.saturating_sub(prev_w) as f64;
                (
                    dr / elapsed_secs,
                    dw / elapsed_secs,
                    (dr + dw) / (1024.0 * 1024.0),
                )
            }
            _ => (0.0, 0.0, 0.0),
        };
        self.last_disk_bytes = current_disk_bytes;

        let mut interfaces = Vec::new();
        let mut total_rx_bps = 0.0_f64;
        let mut total_tx_bps = 0.0_f64;
        for (name, data) in &self.networks {
            let rx_bps = data.received() as f64 / elapsed_secs;
            let tx_bps = data.transmitted() as f64 / elapsed_secs;
            total_rx_bps += rx_bps;
            total_tx_bps += tx_bps;
            interfaces.push(InterfaceMetric {
                name: name.clone(),
                rx_bps: round2(rx_bps),
                tx_bps: round2(tx_bps),
            });
        }
        interfaces.sort_by(|a, b| a.name.cmp(&b.name));

        MetricSample {
            server: server_id.to_string(),
            sample_id: Uuid::now_v7(),
            timestamp: Utc::now(),
            cpu_usage: round2(cpu_usage),
            ram_usage: round2(ram_usage),
            disk_io: round2(disk_io_mb),
            swap_usage: round2(swap_usage),
            disk_usage: round2(max_disk_percent),
            disk_read_bps: round2(disk_read_bps),
            disk_write_bps: round2(disk_write_bps),
            net_rx_bps: round2(total_rx_bps),
            net_tx_bps: round2(total_tx_bps),
            load_1m: round2(load_1m),
            uptime_seconds: System::uptime(),
            details: MetricDetails {
                per_core_cpu,
                load_avg: [
                    round2(load_avg_raw[0]),
                    round2(load_avg_raw[1]),
                    round2(load_avg_raw[2]),
                ],
                mounts: mount_map.into_values().collect(),
                interfaces,
            },
        }
    }
}

impl Default for SystemCollector {
    fn default() -> Self {
        Self::new()
    }
}

fn clamp_percent(value: f64) -> f64 {
    if !value.is_finite() {
        return 0.0;
    }
    value.clamp(0.0, 100.0)
}

fn round2(value: f64) -> f64 {
    if !value.is_finite() {
        return 0.0;
    }
    (value * 100.0).round() / 100.0
}

#[cfg(target_os = "linux")]
fn read_load_average() -> [f64; 3] {
    if let Ok(load) = procfs::LoadAverage::new() {
        return [f64::from(load.one), f64::from(load.five), f64::from(load.fifteen)];
    }
    let fallback = System::load_average();
    [fallback.one, fallback.five, fallback.fifteen]
}

#[cfg(not(target_os = "linux"))]
fn read_load_average() -> [f64; 3] {
    let load = System::load_average();
    [load.one, load.five, load.fifteen]
}

#[cfg(target_os = "linux")]
fn read_total_disk_io_bytes() -> Option<(u64, u64)> {
    let stats = procfs::diskstats().ok()?;
    let mut read_sectors: u64 = 0;
    let mut write_sectors: u64 = 0;
    for stat in stats {
        if stat.name.starts_with("loop") || stat.name.starts_with("ram") {
            continue;
        }
        read_sectors = read_sectors.saturating_add(stat.sectors_read);
        write_sectors = write_sectors.saturating_add(stat.sectors_written);
    }
    Some((
        read_sectors.saturating_mul(512),
        write_sectors.saturating_mul(512),
    ))
}

#[cfg(not(target_os = "linux"))]
fn read_total_disk_io_bytes() -> Option<(u64, u64)> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collector_produces_valid_v1_sample_and_inventory() {
        let mut collector = SystemCollector::new();
        let server_id = "00000000-0000-0000-0000-000000000001";
        let inv = collector.collect_inventory(server_id);
        assert_eq!(inv.server, server_id);
        assert_eq!(inv.agent_version, env!("CARGO_PKG_VERSION"));
        assert!(inv.cpu_cores.unwrap_or(0) >= 1);

        let sample = collector.collect_sample(server_id);
        assert_eq!(sample.server, server_id);
        assert!((0.0..=100.0).contains(&sample.cpu_usage));
        assert!((0.0..=100.0).contains(&sample.ram_usage));
        assert!((0.0..=100.0).contains(&sample.disk_usage));
        assert!((0.0..=100.0).contains(&sample.swap_usage));
        assert!(sample.net_rx_bps >= 0.0);
        assert!(sample.net_tx_bps >= 0.0);
    }
}
