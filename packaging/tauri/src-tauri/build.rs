fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["family_switch"])),
    )
    .expect("failed to build ThreadDesk permissions")
}
