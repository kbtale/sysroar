use std::collections::BTreeMap;
use std::time::Instant;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sysinfo::{Components, Disks, Networks, ProcessRefreshKind, ProcessesToUpdate, System};
use uuid::Uuid;
use crate::docker::DockerContainerMetric;

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
    #[serde(default)]
    pub inodes_used_percent: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InterfaceMetric {
    pub name: String,
    pub rx_bps: f64,
    pub tx_bps: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProcessMetric {
    pub pid: u32,
    pub name: String,
    pub cpu_percent: f64,
    pub mem_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TemperatureMetric {
    pub label: String,
    pub celsius: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SystemdUnitMetric {
    pub name: String,
    pub active_state: String,
    pub sub_state: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct MetricDetails {
    pub per_core_cpu: Vec<f64>,
    pub load_avg: [f64; 3],
    pub mounts: Vec<MountMetric>,
    pub interfaces: Vec<InterfaceMetric>,
    #[serde(default)]
    pub cpu_iowait_percent: Option<f64>,
    #[serde(default)]
    pub cpu_steal_percent: Option<f64>,
    #[serde(default)]
    pub disk_iops_read: f64,
    #[serde(default)]
    pub disk_iops_write: f64,
    #[serde(default)]
    pub disk_util_percent: f64,
    #[serde(default)]
    pub process_count: usize,
    #[serde(default)]
    pub top_processes: Vec<ProcessMetric>,
    #[serde(default)]
    pub temperatures: Vec<TemperatureMetric>,
    #[serde(default)]
    pub systemd_units: Vec<SystemdUnitMetric>,
    #[serde(default)]
    pub docker_containers: Vec<DockerContainerMetric>,
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

#[derive(Debug, Clone, Copy)]
struct DiskStatsSnapshot {
    read_bytes: u64,
    write_bytes: u64,
    reads_completed: u64,
    writes_completed: u64,
    io_time_ms: u64,
}

#[derive(Debug, Clone, Copy)]
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
struct CpuTicksSnapshot {
    total: u64,
    iowait: u64,
    steal: u64,
}

pub struct SystemCollector {
    sys: System,
    disks: Disks,
    networks: Networks,
    components: Components,
    last_collected_at: Instant,
    last_disk_stats: Option<DiskStatsSnapshot>,
    last_cpu_ticks: Option<CpuTicksSnapshot>,
}

impl SystemCollector {
    pub fn new() -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();
        let disks = Disks::new_with_refreshed_list();
        let networks = Networks::new_with_refreshed_list();
        let components = Components::new_with_refreshed_list();
        let last_disk_stats = read_disk_stats_snapshot();
        let last_cpu_ticks = read_cpu_ticks_snapshot();
        Self {
            sys,
            disks,
            networks,
            components,
            last_collected_at: Instant::now(),
            last_disk_stats,
            last_cpu_ticks,
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
        self.sys.refresh_processes_specifics(
            ProcessesToUpdate::All,
            true,
            ProcessRefreshKind::nothing().with_cpu().with_memory(),
        );
        self.disks.refresh(true);
        self.networks.refresh(true);
        self.components.refresh(true);

        let cpu_usage = clamp_percent(f64::from(self.sys.global_cpu_usage()));
        let cpu_count = self.sys.cpus().len().max(1) as f64;
        let per_core_cpu: Vec<f64> = self
            .sys
            .cpus()
            .iter()
            .map(|c| round2(clamp_percent(f64::from(c.cpu_usage()))))
            .collect();

        let current_cpu_ticks = read_cpu_ticks_snapshot();
        let (cpu_iowait_percent, cpu_steal_percent) =
            match (self.last_cpu_ticks, current_cpu_ticks) {
                (Some(prev), Some(cur)) => {
                    let total_delta = cur.total.saturating_sub(prev.total);
                    if total_delta > 0 {
                        let iowait = clamp_percent(
                            (cur.iowait.saturating_sub(prev.iowait) as f64 / total_delta as f64)
                                * 100.0,
                        );
                        let steal = clamp_percent(
                            (cur.steal.saturating_sub(prev.steal) as f64 / total_delta as f64)
                                * 100.0,
                        );
                        (Some(round2(iowait)), Some(round2(steal)))
                    } else {
                        (Some(0.0), Some(0.0))
                    }
                }
                _ => (None, None),
            };
        self.last_cpu_ticks = current_cpu_ticks;

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

        let inode_map = read_mount_inodes();
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
            let inodes_used_percent = inode_map.get(&mount).copied();
            mount_map.insert(
                mount.clone(),
                MountMetric {
                    mount,
                    used_percent: round2(pct),
                    total_bytes: total,
                    available_bytes: available,
                    inodes_used_percent,
                },
            );
        }

        let current_disk_stats = read_disk_stats_snapshot();
        let (disk_read_bps, disk_write_bps, disk_io_mb, disk_iops_read, disk_iops_write, disk_util_percent) =
            match (self.last_disk_stats, current_disk_stats) {
                (Some(prev), Some(cur)) => {
                    let dr = cur.read_bytes.saturating_sub(prev.read_bytes) as f64;
                    let dw = cur.write_bytes.saturating_sub(prev.write_bytes) as f64;
                    let r_ops = cur.reads_completed.saturating_sub(prev.reads_completed) as f64;
                    let w_ops = cur.writes_completed.saturating_sub(prev.writes_completed) as f64;
                    let io_ms = cur.io_time_ms.saturating_sub(prev.io_time_ms) as f64;
                    let util = clamp_percent((io_ms / (elapsed_secs * 1000.0)) * 100.0);
                    (
                        dr / elapsed_secs,
                        dw / elapsed_secs,
                        (dr + dw) / (1024.0 * 1024.0),
                        r_ops / elapsed_secs,
                        w_ops / elapsed_secs,
                        util,
                    )
                }
                _ => (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            };
        self.last_disk_stats = current_disk_stats;

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

        let process_count = self.sys.processes().len();
        let mut proc_list: Vec<ProcessMetric> = self
            .sys
            .processes()
            .iter()
            .map(|(pid, proc_info)| ProcessMetric {
                pid: pid.as_u32(),
                name: proc_info.name().to_string_lossy().chars().take(64).collect(),
                cpu_percent: round2(clamp_percent(f64::from(proc_info.cpu_usage()) / cpu_count)),
                mem_bytes: proc_info.memory(),
            })
            .collect();
        proc_list.sort_by(|a, b| {
            b.cpu_percent
                .total_cmp(&a.cpu_percent)
                .then_with(|| b.mem_bytes.cmp(&a.mem_bytes))
        });
        proc_list.truncate(8);

        let temperatures: Vec<TemperatureMetric> = self
            .components
            .iter()
            .filter_map(|comp| {
                let temp = f64::from(comp.temperature()?);
                if !temp.is_finite() {
                    return None;
                }
                Some(TemperatureMetric {
                    label: comp.label().chars().take(48).collect(),
                    celsius: round2(temp),
                })
            })
            .take(12)
            .collect();

        let systemd_units = read_systemd_units();

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
                cpu_iowait_percent,
                cpu_steal_percent,
                disk_iops_read: round2(disk_iops_read),
                disk_iops_write: round2(disk_iops_write),
                disk_util_percent: round2(disk_util_percent),
                process_count,
                top_processes: proc_list,
                temperatures,
                systemd_units,
                docker_containers: Vec::new(),
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
    use procfs::Current;

    if let Ok(load) = procfs::LoadAverage::current() {
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
fn read_cpu_ticks_snapshot() -> Option<CpuTicksSnapshot> {
    use procfs::CurrentSI;

    let stats = procfs::KernelStats::current().ok()?;
    let cpu = stats.total;
    let iowait = cpu.iowait.unwrap_or(0);
    let irq = cpu.irq.unwrap_or(0);
    let softirq = cpu.softirq.unwrap_or(0);
    let steal = cpu.steal.unwrap_or(0);
    let guest = cpu.guest.unwrap_or(0);
    let guest_nice = cpu.guest_nice.unwrap_or(0);
    let total = cpu
        .user
        .saturating_add(cpu.nice)
        .saturating_add(cpu.system)
        .saturating_add(cpu.idle)
        .saturating_add(iowait)
        .saturating_add(irq)
        .saturating_add(softirq)
        .saturating_add(steal)
        .saturating_add(guest)
        .saturating_add(guest_nice);
    Some(CpuTicksSnapshot { total, iowait, steal })
}

#[cfg(not(target_os = "linux"))]
fn read_cpu_ticks_snapshot() -> Option<CpuTicksSnapshot> {
    None
}

#[cfg(target_os = "linux")]
fn read_disk_stats_snapshot() -> Option<DiskStatsSnapshot> {
    let stats = procfs::diskstats().ok()?;
    let mut read_sectors: u64 = 0;
    let mut write_sectors: u64 = 0;
    let mut reads_completed: u64 = 0;
    let mut writes_completed: u64 = 0;
    let mut io_time_ms: u64 = 0;
    for stat in stats {
        if stat.name.starts_with("loop") || stat.name.starts_with("ram") {
            continue;
        }
        read_sectors = read_sectors.saturating_add(stat.sectors_read);
        write_sectors = write_sectors.saturating_add(stat.sectors_written);
        reads_completed = reads_completed.saturating_add(stat.reads);
        writes_completed = writes_completed.saturating_add(stat.writes);
        io_time_ms = io_time_ms.saturating_add(stat.time_in_progress);
    }
    Some(DiskStatsSnapshot {
        read_bytes: read_sectors.saturating_mul(512),
        write_bytes: write_sectors.saturating_mul(512),
        reads_completed,
        writes_completed,
        io_time_ms,
    })
}

#[cfg(not(target_os = "linux"))]
fn read_disk_stats_snapshot() -> Option<DiskStatsSnapshot> {
    None
}

pub fn parse_df_inodes_output(output: &str) -> BTreeMap<String, f64> {
    let mut map = BTreeMap::new();
    for line in output.lines().skip(1) {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 6 {
            continue;
        }
        let pct_str = parts[4].trim_end_matches('%');
        if let Ok(pct) = pct_str.parse::<f64>() {
            let mount = parts[5..].join(" ");
            map.insert(mount, round2(clamp_percent(pct)));
        }
    }
    map
}

#[cfg(unix)]
fn read_mount_inodes() -> BTreeMap<String, f64> {
    let Ok(out) = std::process::Command::new("df").args(["-Pi"]).output() else {
        return BTreeMap::new();
    };
    if !out.status.success() {
        return BTreeMap::new();
    }
    parse_df_inodes_output(&String::from_utf8_lossy(&out.stdout))
}

#[cfg(not(unix))]
fn read_mount_inodes() -> BTreeMap<String, f64> {
    BTreeMap::new()
}

pub fn parse_systemd_units_output(output: &str, max_units: usize) -> Vec<SystemdUnitMetric> {
    let mut units = Vec::new();
    for line in output.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let parts: Vec<&str> = trimmed.split_whitespace().collect();
        if parts.len() < 4 {
            continue;
        }
        let name = parts[0].trim_start_matches('●').trim();
        if name.is_empty() {
            continue;
        }
        units.push(SystemdUnitMetric {
            name: name.chars().take(80).collect(),
            active_state: parts[2].to_string(),
            sub_state: parts[3].to_string(),
        });
        if units.len() >= max_units {
            break;
        }
    }
    units
}

#[cfg(target_os = "linux")]
fn read_systemd_units() -> Vec<SystemdUnitMetric> {
    let Ok(out) = std::process::Command::new("systemctl")
        .args([
            "list-units",
            "--type=service",
            "--state=failed,running",
            "--no-pager",
            "--no-legend",
            "--plain",
        ])
        .output()
    else {
        return Vec::new();
    };
    if !out.status.success() {
        return Vec::new();
    }
    parse_systemd_units_output(&String::from_utf8_lossy(&out.stdout), 15)
}

#[cfg(not(target_os = "linux"))]
fn read_systemd_units() -> Vec<SystemdUnitMetric> {
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collector_produces_valid_v2_sample_and_inventory() {
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
        assert!(sample.details.process_count >= 1);
        assert!(!sample.details.top_processes.is_empty());
        assert!(sample.details.top_processes.len() <= 8);
    }

    #[test]
    fn parses_df_inodes_and_systemd_units() {
        let df_out = "Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/sda1 1000 120 880 12% /\ntmpfs 500 5 495 1% /run\n";
        let inodes = parse_df_inodes_output(df_out);
        assert_eq!(inodes.get("/"), Some(&12.0));
        assert_eq!(inodes.get("/run"), Some(&1.0));

        let sys_out = "nginx.service loaded active running A high performance web server\npostgres.service loaded failed failed PostgreSQL\n";
        let units = parse_systemd_units_output(sys_out, 10);
        assert_eq!(units.len(), 2);
        assert_eq!(units[0].name, "nginx.service");
        assert_eq!(units[0].active_state, "active");
        assert_eq!(units[1].active_state, "failed");
    }
}
