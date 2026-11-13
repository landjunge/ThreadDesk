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
/// A handshake line is one short URL; anything longer is not trusted.
const MAX_HANDSHAKE_BYTES: usize = 4096;
/// Cap one diagnostic line after sanitizing; keep the log readable.
const MAX_LOG_LINE_CHARS: usize = 400;

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

fn append_startup_error(path: &Path, message: &str) {
    let mut options = OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    if let Ok(mut file) = options.open(path) {
        let _ = writeln!(file, "[host] {message}");
    }
}

/// Keep only bounded, sanitized diagnostics: no request bodies, profile
/// content or obvious credential material. The home path is shortened, long
/// lines are cut, and lines with secret markers are dropped.
fn sanitize_line(line: &str) -> Option<String> {
    let mut value = line.replace('\r', "");
    if let Some(home) = std::env::var_os("HOME") {
        let home = home.to_string_lossy();
        if !home.is_empty() {
            value = value.replace(home.as_ref(), "~");
        }
    }
    let lower = value.to_ascii_lowercase();
    const SECRET_MARKERS: [&str; 6] = [
        "authorization:",
        "bearer ",
        "password",
        "secret",
        "token",
        "private key",
    ];
    if SECRET_MARKERS.iter().any(|marker| lower.contains(marker)) {
        return None;
    }
    let clean: String = value
        .chars()
        .filter(|character| !character.is_control() || *character == '\t')
        .take(MAX_LOG_LINE_CHARS)
        .collect();
    if clean.trim().is_empty() {
        None
    } else {
        Some(clean)
    }
}

/// Drain the child's stderr line by line. Reading continues after the cap, so a
/// full log can never block the backend through a full pipe (no SIGPIPE /
/// backpressure). Only sanitized lines are persisted.
fn drain_stderr(mut stderr: ChildStderr, sink: Box<dyn Write + Send>, cap: u64) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let mut sink = sink;
        let mut written: u64 = 0;
        let mut pending: Vec<u8> = Vec::new();
        let mut buffer = [0u8; 8192];
        loop {
            match stderr.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(read) => {
                    pending.extend_from_slice(&buffer[..read]);
                    while let Some(position) = pending.iter().position(|byte| *byte == b'\n') {
                        let line: Vec<u8> = pending.drain(..=position).collect();
                        if let Some(clean) = sanitize_line(&String::from_utf8_lossy(&line)) {
                            if written < cap {
                                let mut bytes = clean.into_bytes();
                                bytes.push(b'\n');
                                let room = (cap - written) as usize;
                                let take = room.min(bytes.len());
                                let _ = sink.write_all(&bytes[..take]);
                                written += take as u64;
                            }
                        }
                    }
                    if pending.len() > 8192 {
                        pending.clear();
                    }
                }
            }
        }
        if !pending.is_empty() {
            if let Some(clean) = sanitize_line(&String::from_utf8_lossy(&pending)) {
                if written < cap {
                    let mut bytes = clean.into_bytes();
                    bytes.push(b'\n');
                    let room = (cap - written) as usize;
                    let take = room.min(bytes.len());
                    let _ = sink.write_all(&bytes[..take]);
                }
            }
        }
        let _ = sink.flush();
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

            let stderr = owned
                .child_mut()
                .stderr
                .take()
                .ok_or("Backend stderr unavailable")?;
            let _ = drain_stderr(stderr, Box::new(log_file), STDERR_LOG_CAP);
            let stdout = owned
                .child_mut()
                .stdout
                .take()
                .ok_or("Backend stdout unavailable")?;
            let url = match read_ready_line(stdout, READY_TIMEOUT) {
                Ok(line) => match validate_ready_url(&line) {
                    Ok(url) => url,
                    Err(error) => {
                        let message = format!("{error}. Log: {}", log_path.display());
                        append_startup_error(&log_path, &message);
                        show_startup_error(&message);
                        return Err(message.into());
                    }
                },
                Err(ReadyError::Timeout) => {
                    let message = format!(
                        "Das lokale Backend meldete sich nicht innerhalb von {} Sekunden. Log: {}",
                        READY_TIMEOUT.as_secs(),
                        log_path.display()
                    );
                    append_startup_error(&log_path, &message);
                    show_startup_error(&message);
                    return Err(message.into());
                }
                Err(ReadyError::Exited) => {
                    let status = wait_bounded(owned.child_mut(), Duration::from_secs(2))
                        .and_then(|value| value.code());
                    let message = format!(
                        "Das lokale Backend endete vor der Bereitschaft (Exit {status:?}). Log: {}",
                        log_path.display()
                    );
                    append_startup_error(&log_path, &message);
                    show_startup_error(&message);
                    return Err(message.into());
                }
                Err(ReadyError::Io(error)) | Err(ReadyError::Protocol(error)) => {
                    let message = format!(
                        "Das lokale Backend lieferte keine gültige Bereitschaft ({error}). Log: {}",
                        log_path.display()
                    );
                    append_startup_error(&log_path, &message);
                    show_startup_error(&message);
                    return Err(message.into());
                }
            };
            let origin = url.origin().ascii_serialization();
            app.add_capability(tauri::ipc::CapabilityBuilder::new("local-family-switch")
                .local(false).window("main").remote(format!("{}/*", origin))
                .permission("allow-family-switch"))?;
            app.manage(FamilyHost { origin: origin.clone(), home: app.path().home_dir()?, busy: Arc::new(AtomicBool::new(false)) });
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
                .build()?;
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
        drain_stderr, open_private_log, read_ready_line, sanitize_line, stop_owned_child,
        validate_ready_url, workspace_dir, workspace_dir_for, ReadyError,
    };
    use std::io::Write;
    use std::process::Stdio;
    use std::sync::atomic::{AtomicUsize, Ordering};
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
    fn diagnostics_are_sanitized_and_bounded() {
        assert_eq!(sanitize_line("error: boom").as_deref(), Some("error: boom"));
        assert!(sanitize_line("Authorization: Bearer abc").is_none());
        assert!(sanitize_line("password=hunter2").is_none());
        assert!(sanitize_line("token: abc").is_none());
        assert!(sanitize_line("\u{7}\u{8}").is_none());
        let long = "x".repeat(1000);
        assert!(sanitize_line(&long).expect("line").chars().count() <= 400);
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
        let mut child = spawn(
            "i=0; while [ $i -lt 4000 ]; do echo 'line with diagnostics' >&2; i=$((i+1)); done",
            Stdio::null(),
        );
        let stderr = child.stderr.take().expect("stderr");
        let handle = drain_stderr(stderr, Box::new(file), 4096);
        let status = child.wait().expect("child exit");
        handle.join().expect("drain join");
        assert!(status.success());
        let size = std::fs::metadata(&path).expect("log metadata").len();
        assert!(size <= 4096, "log grew past cap: {size}");
        assert!(size > 0, "log should contain the beginning of stderr");
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
