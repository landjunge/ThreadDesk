use std::{
    ffi::OsString,
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{atomic::AtomicBool, Arc, Mutex},
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

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

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![family_switch])
        .setup(|app| {
            let data = workspace_dir();
            let binary = app.path().resource_dir()?.join("bin/ThreadDeskServer");
            if !binary.is_file() {
                return Err(format!("Backend missing: {}", binary.display()).into());
            }
            let mut child = Command::new(&binary)
                .env("THREADDESK_HOME", &data)
                .env("THREADDESK_STORAGE", "json")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()?;

            let stdout = child.stdout.take().ok_or("Backend stdout unavailable")?;
            let mut line = String::new();
            if BufReader::new(stdout).read_line(&mut line)? == 0 {
                let _ = child.wait();
                return Err("Backend exited without a ready URL".into());
            }
            let address = line.strip_prefix("THREADDESK_URL ").ok_or("Unexpected backend handshake")?.trim();
            let url: tauri::Url = address.parse()?;
            if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.port().is_none() {
                return Err("Backend did not return a loopback-only address".into());
            }
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
            app.manage(Backend(Mutex::new(child)));
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
                        let _ = child.kill();
                        let _ = child.wait();
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
    use super::{workspace_dir, workspace_dir_for};

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
}
