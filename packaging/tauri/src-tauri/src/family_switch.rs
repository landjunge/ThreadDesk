//! Bounded native-only family CLI adapter. No shell or browser-supplied argv.
use serde_json::Value;
use std::{
    io::Read,
    path::Path,
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc,
    },
    time::Duration,
};

pub const PRODUCTS: [&str; 5] = [
    "kirabridge",
    "threaddesk",
    "4allpass",
    "tollgate",
    "agent-authority",
];

pub fn arguments(target: &str, native_pid: u32) -> Result<Vec<String>, String> {
    if !PRODUCTS.contains(&target) {
        return Err("Unknown family product".into());
    }
    Ok([
        "--principal",
        "local",
        "family",
        "switch",
        target,
        "--source-pid",
        &native_pid.to_string(),
    ]
    .iter()
    .map(|s| s.to_string())
    .collect())
}

pub fn receipt(exit_ok: bool, bytes: &[u8], target: &str) -> &'static str {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return "uncertain";
    };
    if value.get("success") == Some(&Value::Bool(false)) {
        return if !exit_ok
            && value.get("execution_outcome_unknown") == Some(&Value::Bool(false))
            && value
                .pointer("/error/code")
                .and_then(Value::as_str)
                .is_some()
            && value
                .pointer("/error/message")
                .and_then(Value::as_str)
                .is_some()
        {
            "failed"
        } else {
            "uncertain"
        };
    }
    let bounds = value.get("actual_outer_bounds");
    let geometry = ["x", "y", "width", "height"].iter().all(|key| {
        bounds
            .and_then(|b| b.get(key))
            .and_then(Value::as_f64)
            .is_some_and(|n| n.is_finite() && (!matches!(*key, "width" | "height") || n > 0.0))
    });
    if exit_ok
        && value.get("success") == Some(&Value::Bool(true))
        && value.get("error").is_none()
        && value.get("execution_outcome_unknown") != Some(&Value::Bool(true))
        && value.get("active_product").and_then(Value::as_str) == Some(target)
        && value.get("visible_family_windows").and_then(Value::as_u64) == Some(1)
        && geometry
    {
        "focused"
    } else {
        "uncertain"
    }
}

struct Release(Arc<AtomicBool>);
impl Drop for Release {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

pub fn switch(home: &Path, target: &str, busy: Arc<AtomicBool>) -> Result<String, String> {
    let args = arguments(target, std::process::id())?;
    if busy
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Ok("uncertain".into());
    }
    let release = Release(busy);
    let mut child = Command::new(home.join(".local/bin/kirabridge"))
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Family broker unavailable".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or("Family broker output unavailable")?;
    let (send, receive) = mpsc::sync_channel(1);
    let target = target.to_string();
    // Keep ownership until the original attempt finishes, even if the UI deadline
    // expires. Never kill an uncertain effect or start a second broker attempt.
    std::thread::spawn(move || {
        let _release = release;
        let mut bytes = Vec::new();
        let read = stdout.take(65537).read_to_end(&mut bytes);
        let status = child.wait();
        let outcome = if read.is_ok() && bytes.len() <= 65536 {
            status
                .map(|s| receipt(s.success(), &bytes, &target))
                .unwrap_or("uncertain")
        } else {
            "uncertain"
        };
        let _ = send.send(outcome.to_string());
    });
    Ok(receive
        .recv_timeout(Duration::from_secs(30))
        .unwrap_or_else(|_| "uncertain".into()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_broker_releases_guard_without_claiming_success() {
        let busy = Arc::new(AtomicBool::new(false));
        let home = std::env::temp_dir().join(format!("td-missing-broker-{}", std::process::id()));
        assert!(switch(&home, "threaddesk", busy.clone()).is_err());
        assert!(!busy.load(Ordering::Acquire));
    }

    #[cfg(unix)]
    #[test]
    fn direct_process_uses_native_pid_and_concurrent_attempt_does_not_spawn() {
        use std::{fs, os::unix::fs::PermissionsExt};
        let home = std::env::temp_dir().join(format!(
            "td-family-fixture-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(home.join(".local/bin")).unwrap();
        let executable = home.join(".local/bin/kirabridge");
        let script = format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$0.argv\"\nsleep 0.2\nprintf '%s\\n' '{}'\n",
            good()
        );
        fs::write(&executable, script).unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
        let busy = Arc::new(AtomicBool::new(false));
        let first_home = home.clone();
        let first_busy = busy.clone();
        let first = std::thread::spawn(move || switch(&first_home, "threaddesk", first_busy));
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        while !executable.with_extension("argv").exists() && std::time::Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(busy.load(Ordering::Acquire));
        assert_eq!(
            switch(&home, "4allpass", busy.clone()).unwrap(),
            "uncertain"
        );
        assert_eq!(first.join().unwrap().unwrap(), "focused");
        assert!(!busy.load(Ordering::Acquire));
        let observed = fs::read_to_string(executable.with_extension("argv")).unwrap();
        assert_eq!(
            observed.lines().collect::<Vec<_>>(),
            arguments("threaddesk", std::process::id()).unwrap()
        );
        fs::remove_dir_all(home).unwrap();
    }
    fn good() -> Value {
        serde_json::json!({"success":true,"active_product":"threaddesk",
        "actual_outer_bounds":{"x":-200,"y":20,"width":1358,"height":664},"visible_family_windows":1})
    }
    #[test]
    fn only_fixed_catalog_and_native_pid_enter_argv() {
        assert_eq!(
            arguments("threaddesk", 42).unwrap(),
            [
                "--principal",
                "local",
                "family",
                "switch",
                "threaddesk",
                "--source-pid",
                "42"
            ]
        );
        for target in [
            "../app",
            "threaddesk;quit",
            "https://host",
            "",
            "ThreadDesk",
        ] {
            assert!(arguments(target, 42).is_err());
        }
    }
    #[test]
    fn exact_receipt_required_not_exit_or_task_wrapper() {
        assert_eq!(
            receipt(true, &serde_json::to_vec(&good()).unwrap(), "threaddesk"),
            "focused"
        );
        for value in [
            serde_json::json!({"result":good()}),
            serde_json::json!({"success":true}),
            serde_json::json!("done"),
        ] {
            assert_eq!(
                receipt(true, &serde_json::to_vec(&value).unwrap(), "threaddesk"),
                "uncertain"
            );
        }
        assert_eq!(
            receipt(false, &serde_json::to_vec(&good()).unwrap(), "threaddesk"),
            "uncertain"
        );
        assert_eq!(receipt(true, b"not JSON", "threaddesk"), "uncertain");
        assert_eq!(
            receipt(true, &serde_json::to_vec(&good()).unwrap(), "4allpass"),
            "uncertain"
        );
    }
    #[test]
    fn hidden_peer_geometry_and_error_cannot_be_success() {
        for (pointer, value) in [
            ("/visible_family_windows", serde_json::json!(2)),
            ("/actual_outer_bounds/width", serde_json::json!(0)),
            ("/actual_outer_bounds/y", serde_json::json!("20")),
            ("/execution_outcome_unknown", serde_json::json!(true)),
            ("/error", serde_json::json!({"code":"failed"})),
        ] {
            let mut data = good();
            if let Some(slot) = data.pointer_mut(pointer) {
                *slot = value;
            } else {
                data[pointer.trim_start_matches('/')] = value;
            }
            assert_eq!(
                receipt(true, &serde_json::to_vec(&data).unwrap(), "threaddesk"),
                "uncertain"
            );
        }
        for unknown in [false, true] {
            let data = serde_json::json!({"success":false,"error":{"code":"target_missing","message":"Unavailable"},"execution_outcome_unknown":unknown});
            assert_eq!(
                receipt(false, &serde_json::to_vec(&data).unwrap(), "threaddesk"),
                if unknown { "uncertain" } else { "failed" }
            );
            assert_eq!(
                receipt(true, &serde_json::to_vec(&data).unwrap(), "threaddesk"),
                "uncertain"
            );
        }
    }
}
