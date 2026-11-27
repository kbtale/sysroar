use std::time::Duration;
use bollard::query_parameters::{ListContainersOptionsBuilder, StatsOptionsBuilder};
use bollard::Docker;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use tokio::time::timeout;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DockerContainerMetric {
    pub id: String,
    pub name: String,
    pub image: String,
    pub state: String,
    pub status: String,
    pub cpu_percent: f64,
    pub mem_bytes: u64,
    pub mem_limit_bytes: u64,
    pub mem_percent: f64,
}

fn round2(value: f64) -> f64 {
    if !value.is_finite() {
        return 0.0;
    }
    (value * 100.0).round() / 100.0
}

pub fn compute_container_cpu_percent(
    cpu_total: u64,
    precpu_total: u64,
    sys_cpu: u64,
    presys_cpu: u64,
    online_cpus: u64,
) -> f64 {
    let cpu_delta = cpu_total.saturating_sub(precpu_total) as f64;
    let sys_delta = sys_cpu.saturating_sub(presys_cpu) as f64;
    if sys_delta <= 0.0 || cpu_delta <= 0.0 {
        return 0.0;
    }
    let cpus = online_cpus.max(1) as f64;
    round2(((cpu_delta / sys_delta) * cpus * 100.0).clamp(0.0, cpus * 100.0))
}

pub async fn collect_docker_containers(max_containers: usize) -> Vec<DockerContainerMetric> {
    let Ok(docker) = Docker::connect_with_local_defaults() else {
        return Vec::new();
    };

    let list_opts = ListContainersOptionsBuilder::default().all(true).build();
    let Ok(Ok(summaries)) = timeout(Duration::from_secs(2), docker.list_containers(Some(list_opts))).await else {
        return Vec::new();
    };

    let mut results = Vec::new();
    for summary in summaries.into_iter().take(max_containers) {
        let full_id = summary.id.unwrap_or_default();
        let short_id = full_id.chars().take(12).collect::<String>();
        let name = summary
            .names
            .unwrap_or_default()
            .into_iter()
            .next()
            .unwrap_or_else(|| short_id.clone())
            .trim_start_matches('/')
            .to_string();
        let image = summary.image.unwrap_or_default();
        let state = summary.state.map(|s| s.to_string()).unwrap_or_else(|| "unknown".to_string());
        let status = summary.status.unwrap_or_default();

        let mut cpu_percent = 0.0;
        let mut mem_bytes = 0;
        let mut mem_limit_bytes = 0;
        let mut mem_percent = 0.0;

        if state.eq_ignore_ascii_case("running") && !full_id.is_empty() {
            let stats_opts = StatsOptionsBuilder::default()
                .stream(false)
                .one_shot(true)
                .build();
            let mut stream = docker.stats(&full_id, Some(stats_opts));
            if let Ok(Some(Ok(stat))) = timeout(Duration::from_secs(2), stream.next()).await {
                if let (Some(cpu_stats), Some(precpu_stats)) = (stat.cpu_stats, stat.precpu_stats) {
                    let cpu_total = cpu_stats.cpu_usage.and_then(|u| u.total_usage).unwrap_or(0);
                    let precpu_total = precpu_stats.cpu_usage.and_then(|u| u.total_usage).unwrap_or(0);
                    let sys_cpu = cpu_stats.system_cpu_usage.unwrap_or(0);
                    let presys_cpu = precpu_stats.system_cpu_usage.unwrap_or(0);
                    let online_cpus = u64::from(cpu_stats.online_cpus.unwrap_or(1));
                    cpu_percent = compute_container_cpu_percent(
                        cpu_total,
                        precpu_total,
                        sys_cpu,
                        presys_cpu,
                        online_cpus,
                    );
                }
                if let Some(mem_stats) = stat.memory_stats {
                    mem_bytes = mem_stats.usage.unwrap_or(0);
                    mem_limit_bytes = mem_stats.limit.unwrap_or(0);
                    if mem_limit_bytes > 0 {
                        mem_percent = round2(
                            ((mem_bytes as f64 / mem_limit_bytes as f64) * 100.0).clamp(0.0, 100.0),
                        );
                    }
                }
            }
        }

        results.push(DockerContainerMetric {
            id: short_id,
            name,
            image,
            state,
            status,
            cpu_percent,
            mem_bytes,
            mem_limit_bytes,
            mem_percent,
        });
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn computes_container_cpu_percentage_safely() {
        assert_eq!(compute_container_cpu_percent(200, 100, 1000, 500, 2), 40.0);
        assert_eq!(compute_container_cpu_percent(100, 200, 1000, 500, 2), 0.0);
        assert_eq!(compute_container_cpu_percent(200, 100, 500, 500, 2), 0.0);
    }
}
