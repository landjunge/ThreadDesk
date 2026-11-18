# Whiteboard: ersetzen und entfernen

Ein Board hält das Gültige. `whiteboard.entry.remove` löscht eine Eintragsdatei und ist beim zweiten Aufruf erfolgreich. Derselbe `external_key` im selben Board gibt bei gleichem Inhalt den vorhandenen Eintrag zurück und ersetzt bei anderem Inhalt den alten. `supersedes` entfernt die genannten Einträge desselben Boards. `expires_at` (ISO-Zeit) entfernt abgelaufene Einträge beim nächsten Lesen oder Schreiben. Es gibt keinen Zeitgeber und kein Archiv.

CLI: `td whiteboard remove <thread> <entry>`.

# Whiteboard: replace and remove

A board keeps what is still valid. `whiteboard.entry.remove` deletes one entry file and succeeds again on a second call. The same `external_key` on the same board returns the existing entry when the content matches and replaces it when the content differs. `supersedes` removes those entries on that board. `expires_at` (ISO time) removes expired entries on the next read or write. There is no timer and no archive.

CLI: `td whiteboard remove <thread> <entry>`.
