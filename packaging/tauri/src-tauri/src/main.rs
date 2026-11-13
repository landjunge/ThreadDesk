use std::{
    ffi::OsString,
    fs::{File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStderr, ChildStdout, Command, Stdio},
    sync::{
        atomic::AtomicBool,
        mpsc,
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::{fs::OpenOptionsExt, process::CommandExt};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// The backend prints its URL once it is listening. Keep the host's wait
/// bounded so a wedged or exited backend cannot block the window forever.
const READY_TIMEOUT: Duration = Duration::from_secs(30);
/// Startup diagnostics are useful, but never unbounded: cap the private log.
const STDERR_LOG_CAP: u64 = 256 * 1024;
/// Reserve room inside the cap so the final "other lines" summary is always
/// written even when classified codes fill the budget.
const SUMMARY_RESERVE: u64 = 128;
/// A handshake line is one short URL; anything longer is not trusted.
const MAX_HANDSHAKE_BYTES: usize = 4096;

struct Backend(Mutex<Child>);
mod family_switch;
struct FamilyHost {
    origin: String,
    home: PathBuf,
    busy: Arc<AtomicBool>,
}

#[tauri::command]
async fn family_switch(
    window: tauri::WebviewWindow,
    host: tauri::State<'_, FamilyHost>,
    target: String,
) -> Result<String, String> {
    if window.label() != "main"
        || window
            .url()
            .map_err(|_| "Window identity unavailable")?
            .origin()
            .ascii_serialization()
            != host.origin
    {
        return Err("Family switch is restricted to the owned local main window".into());
    }
    // The browser supplies only target. PID and executable path are native-owned.
    let home = host.home.clone();
    let busy = host.busy.clone();
    tauri::async_runtime::spawn_blocking(move || family_switch::switch(&home, &target, busy))
        .await
        .unwrap_or_else(|_| Ok("uncertain".into()))
}

/// The same workspace the rest of ThreadDesk already uses.
fn workspace_dir() -> PathBuf {
    workspace_dir_for(
        std::env::var_os("THREADDESK_HOME"),
        std::env::var_os("HOME"),
    )
}

fn workspace_dir_for(configured: Option<OsString>, home: Option<OsString>) -> PathBuf {
    if let Some(path) = configured.filter(|value| !value.is_empty()) {
        return PathBuf::from(path);
    }
    let home = home
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    home.join(".threaddesk")
}

#[derive(Debug)]
enum ReadyError {
    Timeout,
    Exited,
    Protocol(String),
    Io(String),
}

/// Startup diagnostics live in the app's own log directory. The file is
/// created `0600` in a `0700` directory, never follows a symlink, must be a
/// regular file, and is re-chmodded if it already existed permissively.
fn open_private_log(path: &Path) -> io::Result<File> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700))?;
        }
    }
    let mut options = OpenOptions::new();
    options.create(true).write(true).truncate(true);
    #[cfg(unix)]
    {
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let file = options.open(path)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::Other,
            "startup log is not a regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(file)
}

/// One bounded sink shared by the drain thread and host messages. A single
/// mutex serializes writes, so the shared file offset cannot interleave, and
/// the byte budget covers **both** sources.
struct BoundedLog {
    file: File,
    written: u64,
    cap: u64,
}

impl BoundedLog {
    fn new(file: File, cap: u64) -> Self {
        Self {
            file,
            written: 0,
            cap,
        }
    }

    fn write_record(&mut self, text: &str) {
        self.write_limited(text, self.cap.saturating_sub(SUMMARY_RESERVE));
    }

    fn write_summary(&mut self, text: &str) {
        self.write_limited(text, self.cap);
    }

    fn write_limited(&mut self, text: &str, limit: u64) {
        if self.written >= limit {
            return;
        }
        let room = (limit - self.written) as usize;
        let take = room.min(text.len());
        if take == 0 {
            return;
        }
        if self.file.write_all(&text.as_bytes()[..take]).is_ok() {
            self.written += take as u64;
        }
    }

    fn flush(&mut self) {
        let _ = self.file.flush();
    }
}

/// Structured allowlist: persist only fixed startup codes, never raw backend
/// text. Backend stderr carries Python tracebacks, uvicorn errors and the
/// desktop-runtime startup errors; arbitrary lines (which could contain
/// workspace/profile text) are counted but not stored.
fn classify_backend_line(line: &str) -> Option<&'static str> {
    let text = line.trim();
    if text.contains("ThreadDesk läuft für diesen Arbeitsbereich bereits") {
        return Some("backend_workspace_locked");
    }
    if text.contains("gespeicherte ThreadDesk-Adresse ist beschädigt") {
        return Some("backend_saved_address_corrupt");
    }
    if text.contains("gespeicherte ThreadDesk-Adresse ist ungültig") {
        return Some("backend_saved_address_invalid");
    }
    if text.contains("lokale ThreadDesk-Adresse ist belegt") {
        return Some("backend_port_in_use");
    }
    if text == "Traceback (most recent call last):" {
        return Some("backend_traceback");
    }
    if text.contains("ThreadDesk backend stopped before it was ready") {
        return Some("backend_stopped_before_ready");
    }
    if text.contains("ThreadDesk backend startup timed out") {
        return Some("backend_startup_timeout");
    }
    None
}

/// Drain the child's stderr and persist only bounded classification counts.
/// Reading continues after the cap, so a full log can never block the backend.
fn drain_stderr(mut stderr: ChildStderr, sink: Arc<Mutex<BoundedLog>>) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let sink = sink;
        let mut pending: Vec<u8> = Vec::new();
        let mut other: u64 = 0;
        let mut buffer = [0u8; 8192];
        loop {
            match stderr.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(read) => {
                    pending.extend_from_slice(&buffer[..read]);
                    while let Some(position) = pending.iter().position(|byte| *byte == b'\n') {
                        let line: Vec<u8> = pending.drain(..=position).collect();
                        let text = String::from_utf8_lossy(&line);
                        match classify_backend_line(&text) {
                            Some(code) => {
                                let record = format!("event=backend_stderr code={code}\n");
                                if let Ok(mut log) = sink.lock() {
                                    log.write_record(&record);
                                }
                            }
                            None => other += 1,
                        }
                    }
                    // Bound the partial line; discard the tail of an oversized
                    // line instead of holding arbitrary workspace text.
                    if pending.len() > 4096 {
                        pending.clear();
                        other += 1;
                    }
                }
            }
        }
        if !pending.is_empty() {
            match classify_backend_line(&String::from_utf8_lossy(&pending)) {
                Some(code) => {
                    let record = format!("event=backend_stderr code={code}\n");
                    if let Ok(mut log) = sink.lock() {
                        log.write_record(&record);
                    }
                }
                None => other += 1,
            }
        }
        if let Ok(mut log) = sink.lock() {
            if other > 0 {
                let record = format!("event=backend_stderr_other count={other}\n");
                log.write_summary(&record);
            }
            log.flush();
        };
    })
}

/// Read exactly one bounded handshake line. Bytes are capped so a child cannot
/// grow the buffer without a newline; the wait is bounded by the caller.
fn read_ready_line(mut stdout: ChildStdout, timeout: Duration) -> Result<String, ReadyError> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut collected: Vec<u8> = Vec::with_capacity(128);
        let mut chunk = [0u8; 256];
        loop {
            match stdout.read(&mut chunk) {
                Ok(0) => {
                    let _ = sender.send(Err(ReadyError::Exited));
                    return;
                }
                Ok(read) => {
                    collected.extend_from_slice(&chunk[..read]);
                    if let Some(position) = collected.iter().position(|byte| *byte == b'\n') {
                        let line = String::from_utf8_lossy(&collected[..=position]).to_string();
                        let _ = sender.send(Ok(line));
                        return;
                    }
                    if collected.len() > MAX_HANDSHAKE_BYTES {
                        let _ = sender.send(Err(ReadyError::Protocol(
                            "backend handshake too long".to_string(),
                        )));
                        return;
                    }
                }
                Err(error) => {
                    let _ = sender.send(Err(ReadyError::Io(error.to_string())));
                    return;
                }
            }
        }
    });
    match receiver.recv_timeout(timeout) {
        Ok(Ok(line)) => Ok(line),
        Ok(Err(error)) => Err(error),
        Err(_) => Err(ReadyError::Timeout),
    }
}

/// Only the host's own child may announce the address, and only loopback.
fn validate_ready_url(line: &str) -> Result<tauri::Url, String> {
    let address = line
        .strip_prefix("THREADDESK_URL ")
        .ok_or("Unexpected backend handshake")?
        .trim();
    let url: tauri::Url = address
        .parse()
        .map_err(|_| "Backend returned an invalid URL".to_string())?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.port() == Some(0)
    {
        return Err("Backend did not return a loopback-only address".to_string());
    }
    Ok(url)
}

fn wait_bounded(child: &mut Child, timeout: Duration) -> Option<std::process::ExitStatus> {
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status),
            Ok(None) if started.elapsed() < timeout => {
                thread::sleep(Duration::from_millis(20));
            }
            _ => return None,
        }
    }
}

/// Cleanup targets exactly the child the host spawned (its own process group on
/// Unix, because one-file bundles fork). It never touches foreign servers, MCP
/// or agent processes, and always reaps the handle.
fn stop_owned_child(child: &mut Child) {
    #[cfg(unix)]
    {
        let pid = child.id() as i32;
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
    }
    if wait_bounded(child, Duration::from_secs(5)).is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Owns the spawned backend until it is handed to the app. Any error after
/// spawn (capability, window build) drops the guard and reaps the child.
struct OwnedChild(Option<Child>);

impl OwnedChild {
    fn new(child: Child) -> Self {
        Self(Some(child))
    }

    fn child_mut(&mut self) -> &mut Child {
        self.0.as_mut().expect("owned child present")
    }

    fn take(&mut self) -> Child {
        self.0.take().expect("owned child present")
    }

    /// Deterministic cleanup: kill/reap now and disarm the Drop backstop.
    fn cleanup(&mut self) {
        if let Some(mut child) = self.0.take() {
            stop_owned_child(&mut child);
        }
    }

    fn is_empty(&self) -> bool {
        self.0.is_none()
    }
}

/// Cleanup happens **before** any modal notification, so a timeout/exit cannot
/// leave the backend alive while the user reads the alert.
fn fail_startup<F>(
    owned: &mut OwnedChild,
    host_log: Option<&Arc<Mutex<BoundedLog>>>,
    message: &str,
    notify: F,
) where
    F: FnOnce(&str),
{
    owned.cleanup();
    if let Some(log) = host_log {
        if let Ok(mut log) = log.lock() {
            log.write_record(&format!("[host] {message}\n"));
            log.flush();
        }
    }
    notify(message);
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            stop_owned_child(&mut child);
        }
    }
}

fn escape_for_alert(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Best-effort native alert. The bounded log path is included so the user can
/// hand it over; there is no automatic retry.
fn show_startup_error(message: &str) {
    let text = escape_for_alert(message);
    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("/usr/bin/osascript")
            .arg("-e")
            .arg(format!(
                "display alert \"ThreadDesk konnte nicht starten\" message \"{text}\" as critical"
            ))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(target_os = "macos"))]
    {
        eprintln!("ThreadDesk konnte nicht starten: {text}");
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![family_switch])
        .setup(|app| {
            let data = workspace_dir();
            let binary = app.path().resource_dir()?.join("bin/ThreadDeskServer");
            if !binary.is_file() {
                return Err(format!("Backend missing: {}", binary.display()).into());
            }
            let log_path = app.path().app_log_dir()?.join("startup.log");
            let log_file = match open_private_log(&log_path) {
                Ok(file) => file,
                Err(error) => {
                    let message = format!(
                        "Der private Startlog konnte nicht sicher geöffnet werden ({error}). Pfad: {}",
                        log_path.display()
                    );
                    show_startup_error(&message);
                    return Err(message.into());
                }
            };
            // Reuse the already validated handle for host messages; never
            // reopen the path (same file/regular/symlink invariants).
            let log = Arc::new(Mutex::new(BoundedLog::new(log_file, STDERR_LOG_CAP)));
            let mut command = Command::new(&binary);
            command
                .env("THREADDESK_HOME", &data)
                .env("THREADDESK_STORAGE", "json")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(unix)]
            command.process_group(0);
            let child = command.spawn()?;
            let mut owned = OwnedChild::new(child);

            let stderr = match owned.child_mut().stderr.take() {
                Some(stderr) => stderr,
                None => {
                    let message = format!(
                        "Das lokale Backend lieferte keinen stderr-Kanal. Log: {}",
                        log_path.display()
                    );
                    fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                    return Err(message.into());
                }
            };
            let _ = drain_stderr(stderr, Arc::clone(&log));
            let stdout = match owned.child_mut().stdout.take() {
                Some(stdout) => stdout,
                None => {
                    let message = format!(
                        "Das lokale Backend lieferte keinen stdout-Kanal. Log: {}",
                        log_path.display()
                    );
                    fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                    return Err(message.into());
                }
            };
            let url = match read_ready_line(stdout, READY_TIMEOUT) {
                Ok(line) => match validate_ready_url(&line) {
                    Ok(url) => url,
                    Err(error) => {
                        let message = format!("{error}. Log: {}", log_path.display());
                        fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                        return Err(message.into());
                    }
                },
                Err(ReadyError::Timeout) => {
                    let message = format!(
                        "Das lokale Backend meldete sich nicht innerhalb von {} Sekunden. Log: {}",
                        READY_TIMEOUT.as_secs(),
                        log_path.display()
                    );
                    fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                    return Err(message.into());
                }
                Err(ReadyError::Exited) => {
                    let status = wait_bounded(owned.child_mut(), Duration::from_secs(2))
                        .and_then(|value| value.code());
                    let message = format!(
                        "Das lokale Backend endete vor der Bereitschaft (Exit {status:?}). Log: {}",
                        log_path.display()
                    );
                    fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                    return Err(message.into());
                }
                Err(ReadyError::Io(error)) | Err(ReadyError::Protocol(error)) => {
                    let message = format!(
                        "Das lokale Backend lieferte keine gültige Bereitschaft ({error}). Log: {}",
                        log_path.display()
                    );
                    fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                    return Err(message.into());
                }
            };
            let origin = url.origin().ascii_serialization();
            let window_setup: Result<(), String> = (|| {
                app.add_capability(tauri::ipc::CapabilityBuilder::new("local-family-switch")
                    .local(false).window("main").remote(format!("{}/*", origin))
                    .permission("allow-family-switch"))
                    .map_err(|error| error.to_string())?;
                app.manage(FamilyHost { origin: origin.clone(), home: app.path().home_dir().map_err(|error| error.to_string())?, busy: Arc::new(AtomicBool::new(false)) });
                WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                    .on_navigation(move |destination| destination.origin().ascii_serialization() == origin)
                    .initialization_script(r#"
                      if (window === window.top) Object.defineProperty(window, '__THREADDESK_FAMILY__', {
                        value:Object.freeze({switchTarget:target => window.__TAURI_INTERNALS__.invoke('family_switch', {target})})
                      });
                    "#)
                    .title("ThreadDesk")
                    .inner_size(1360.0, 780.0)
                    .min_inner_size(940.0, 640.0)
                    .background_color(tauri::window::Color(13, 14, 19, 255))
                    .build()
                    .map_err(|error| error.to_string())?;
                Ok(())
            })();
            if let Err(error) = window_setup {
                let message = format!(
                    "Fenster/Startkonfiguration fehlgeschlagen: {error}. Log: {}",
                    log_path.display()
                );
                fail_startup(&mut owned, Some(&log), &message, show_startup_error);
                return Err(message.into());
            }
            app.manage(Backend(Mutex::new(owned.take())));

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(backend) = window.app_handle().try_state::<Backend>() {
                    if let Ok(mut child) = backend.0.lock() {
                        stop_owned_child(&mut child);
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("ThreadDesk Tauri runtime failed")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{
        classify_backend_line, drain_stderr, fail_startup, open_private_log, read_ready_line,
        stop_owned_child, validate_ready_url, workspace_dir, workspace_dir_for, BoundedLog,
        OwnedChild, ReadyError,
    };
    use std::io::Write;
    use std::process::Stdio;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    static NEXT_DIR: AtomicUsize = AtomicUsize::new(0);

    fn temp_dir(label: &str) -> std::path::PathBuf {
        let id = NEXT_DIR.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "threaddesk-host-{label}-{}-{id}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir");
        dir
    }

    #[cfg(unix)]
    fn spawn(script: &str, stdout: Stdio) -> std::process::Child {
        use std::os::unix::process::CommandExt;
        std::process::Command::new("/bin/sh")
            .arg("-c")
            .arg(script)
            .stdin(Stdio::null())
            .stdout(stdout)
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
            .expect("fixture child")
    }

    #[test]
    fn workspace_is_the_home_store() {
        let home = std::env::var_os("HOME").expect("HOME");
        assert_eq!(
            workspace_dir(),
            workspace_dir_for(std::env::var_os("THREADDESK_HOME"), Some(home))
        );
    }

    #[test]
    fn explicit_workspace_keeps_isolated_runs_out_of_the_home_store() {
        assert_eq!(
            workspace_dir_for(Some("/private/qa/workspace".into()), Some("/owner".into())),
            std::path::PathBuf::from("/private/qa/workspace")
        );
    }

    #[test]
    fn blank_workspace_preserves_the_default_store() {
        assert_eq!(
            workspace_dir_for(Some("".into()), Some("/owner".into())),
            std::path::PathBuf::from("/owner/.threaddesk")
        );
    }

    #[test]
    fn ready_url_must_be_loopback_with_port() {
        assert!(validate_ready_url("THREADDESK_URL http://127.0.0.1:1").is_ok());
        assert!(validate_ready_url("THREADDESK_URL http://localhost:1").is_err());
        assert!(validate_ready_url("THREADDESK_URL http://0.0.0.0:1").is_err());
        assert!(validate_ready_url("THREADDESK_URL https://127.0.0.1:1").is_err());
        assert!(validate_ready_url("THREADDESK_URL http://127.0.0.1").is_err());
        assert!(validate_ready_url("WRONG http://127.0.0.1:1").is_err());
    }

    #[test]
    fn known_backend_lines_map_to_fixed_codes_only() {
        assert_eq!(
            classify_backend_line("RuntimeError: Die lokale ThreadDesk-Adresse ist belegt."),
            Some("backend_port_in_use")
        );
        assert_eq!(
            classify_backend_line("Traceback (most recent call last):"),
            Some("backend_traceback")
        );
        assert_eq!(classify_backend_line("whiteboard note with profile text"), None);
        assert_eq!(classify_backend_line("api_key=abc123"), None);
        assert_eq!(classify_backend_line("{\"secret\":\"x\"}"), None);
    }

    #[cfg(unix)]
    #[test]
    fn cleanup_happens_before_notification() {
        let mut owned = OwnedChild::new(spawn("sleep 30", Stdio::null()));
        let pid = owned.child_mut().id() as i32;
        let mut notified = false;
        fail_startup(&mut owned, None, "timeout", |_message| {
            // The child must already be dead when the modal alert would run.
            let alive = unsafe { libc::kill(pid, 0) } == 0;
            assert!(!alive, "backend must be cleaned up before notification");
            notified = true;
        });
        assert!(notified);
        assert!(owned.is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn ready_line_is_accepted_and_parsed() {
        let mut child = spawn(
            "printf 'THREADDESK_URL http://127.0.0.1:43210\\n'",
            Stdio::piped(),
        );
        let stdout = child.stdout.take().expect("stdout");
        let line = read_ready_line(stdout, Duration::from_secs(2)).expect("ready");
        let url = validate_ready_url(&line).expect("loopback url");
        assert_eq!(url.port(), Some(43210));
        let _ = child.wait();
    }

    #[cfg(unix)]
    #[test]
    fn delayed_ready_still_succeeds() {
        let mut child = spawn(
            "sleep 0.15; printf 'THREADDESK_URL http://127.0.0.1:43211\\n'",
            Stdio::piped(),
        );
        let stdout = child.stdout.take().expect("stdout");
        let line = read_ready_line(stdout, Duration::from_secs(3)).expect("delayed ready");
        assert!(line.contains("43211"));
        let _ = child.wait();
    }

    #[cfg(unix)]
    #[test]
    fn no_ready_times_out_and_own_child_is_reaped() {
        let mut child = spawn("sleep 30", Stdio::piped());
        let stdout = child.stdout.take().expect("stdout");
        let started = Instant::now();
        match read_ready_line(stdout, Duration::from_millis(200)) {
            Err(ReadyError::Timeout) => {}
            other => panic!("expected timeout, got {other:?}"),
        }
        assert!(started.elapsed() < Duration::from_secs(5));
        stop_owned_child(&mut child);
        assert!(child.try_wait().expect("wait").is_some());
    }

    #[cfg(unix)]
    #[test]
    fn exit_before_ready_is_reported() {
        let mut child = spawn("exit 3", Stdio::piped());
        let stdout = child.stdout.take().expect("stdout");
        match read_ready_line(stdout, Duration::from_secs(2)) {
            Err(ReadyError::Exited) => {}
            other => panic!("expected exit, got {other:?}"),
        }
        let _ = child.wait();
    }

    #[cfg(unix)]
    #[test]
    fn oversized_handshake_is_rejected() {
        let mut child = spawn(
            "i=0; while [ $i -lt 5000 ]; do printf A; i=$((i+1)); done; sleep 5",
            Stdio::piped(),
        );
        let stdout = child.stdout.take().expect("stdout");
        match read_ready_line(stdout, Duration::from_secs(2)) {
            Err(ReadyError::Protocol(reason)) => assert!(reason.contains("too long")),
            other => panic!("expected protocol error, got {other:?}"),
        }
        stop_owned_child(&mut child);
        assert!(child.try_wait().expect("wait").is_some());
    }

    #[cfg(unix)]
    #[test]
    fn closed_stdout_with_live_child_is_bounded() {
        let mut child = spawn("exec 1>&-; sleep 30", Stdio::piped());
        let stdout = child.stdout.take().expect("stdout");
        match read_ready_line(stdout, Duration::from_secs(2)) {
            Err(ReadyError::Exited) => {}
            other => panic!("expected exit, got {other:?}"),
        }
        let started = Instant::now();
        stop_owned_child(&mut child);
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(child.try_wait().expect("wait").is_some());
    }

    #[cfg(unix)]
    #[test]
    fn stderr_log_is_capped_but_fully_drained() {
        // Fixture writes to stderr only; stdout is discarded so a full pipe
        // cannot block the child before it exits.
        let dir = temp_dir("stderr");
        let path = dir.join("startup.log");
        let file = open_private_log(&path).expect("log");
        // 4000 classified codes fill the 4096-byte budget; the final summary
        // must still be written from the reserved room. One unclassified line
        // proves the summary path, and its text must never be persisted.
        let mut child = spawn(
            "i=0; while [ $i -lt 4000 ]; do echo 'Traceback (most recent call last):' >&2; i=$((i+1)); done; echo 'secret whiteboard text' >&2",
            Stdio::null(),
        );
        let log = Arc::new(Mutex::new(BoundedLog::new(file, 4096)));
        let stderr = child.stderr.take().expect("stderr");
        let handle = drain_stderr(stderr, Arc::clone(&log));
        let status = child.wait().expect("child exit");
        handle.join().expect("drain join");
        assert!(status.success());
        let size = std::fs::metadata(&path).expect("log metadata").len();
        assert!(size <= 4096, "log grew past cap: {size}");
        assert!(size > 0, "log should contain classified codes");
        let text = std::fs::read_to_string(&path).expect("log");
        assert!(text.contains("code=backend_traceback"));
        assert!(text.contains("event=backend_stderr_other count="));
        assert!(!text.contains("secret whiteboard text"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn host_and_backend_records_share_one_bounded_cap() {
        let dir = temp_dir("shared-cap");
        let path = dir.join("startup.log");
        let file = open_private_log(&path).expect("log");
        let log = Arc::new(Mutex::new(BoundedLog::new(file, 512)));
        let mut handles = Vec::new();
        for tag in ["host", "backend"] {
            let log = Arc::clone(&log);
            handles.push(std::thread::spawn(move || {
                for index in 0..50 {
                    if let Ok(mut log) = log.lock() {
                        let record = format!("event={tag} index={index}\n");
                        if tag == "host" {
                            log.write_record(&record);
                        } else {
                            log.write_summary(&record);
                        }
                    }
                }
            }));
        }
        for handle in handles {
            handle.join().expect("writer");
        }
        let size = std::fs::metadata(&path).expect("log metadata").len();
        assert!(size <= 512, "shared cap exceeded: {size}");
        let text = std::fs::read_to_string(&path).expect("log");
        assert!(text.starts_with("event="));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn existing_permissive_log_file_is_fixed_to_0600() {
        use std::os::unix::fs::PermissionsExt;
        let dir = temp_dir("perms");
        let log_dir = dir.join("ThreadDesk");
        std::fs::create_dir_all(&log_dir).expect("dir");
        let path = log_dir.join("startup.log");
        std::fs::write(&path, "old").expect("old file");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).expect("chmod");
        let mut file = open_private_log(&path).expect("log");
        let _ = writeln!(file, "diagnostic");
        let file_mode = std::fs::metadata(&path).expect("file").permissions().mode() & 0o777;
        let dir_mode = std::fs::metadata(&log_dir).expect("dir").permissions().mode() & 0o777;
        assert_eq!(file_mode, 0o600);
        assert_eq!(dir_mode, 0o700);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn symlinked_log_path_is_refused() {
        let dir = temp_dir("symlink");
        let target = dir.join("elsewhere.log");
        std::fs::write(&target, "do not touch").expect("target");
        let link = dir.join("startup.log");
        std::os::unix::fs::symlink(&target, &link).expect("symlink");
        assert!(open_private_log(&link).is_err());
        assert_eq!(
            std::fs::read_to_string(&target).expect("target read"),
            "do not touch"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
