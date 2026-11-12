# UI-01 · portabler Renderer 1.2.0

ThreadDesk ist die gemeinsame Quelle des bestehenden `networkpunkt-appbar`.
Der feste Katalog enthält KiraBridge, ThreadDesk, 4AllPass, TollGate und Agent
Authority in dieser Reihenfolge. Alle fünf PNGs sind unveränderte Originalderivate;
`networkpunkt-appbar-assets.json` hält Quellenpins und SHA-256 fest.

## Gepinnte lokale Übernahme

Den vollständigen Dateisatz aus `src/threaddesk/ui/static/networkpunkt-appbar-bundle.json`
einer konkreten Commitversion bytegleich übernehmen und gegen
`networkpunkt-appbar-SHA256SUMS` prüfen. Kein CDN, zweites Modul oder automatisches
Update. Der KiraBridge-1.1.1-Fokuspatch ist enthalten: ein verspätetes Dialog-Close
zieht den Tastaturfokus nicht vom inzwischen gewählten Steuerelement zurück.

Originalmotive wirken 32 px groß innerhalb von 44×44-px-Bedienzielen. Version und
Status sind bei Hover und Tastaturfokus zugänglich. Konturen bleiben dezent,
Fokus sichtbar; nur ein bestätigter erlaubter 4AllPass-Unlock darf pulsieren.
Öffnen/Fokussieren bestätigt keine Peer-Verbindung und entsperrt keinen Tresor.

`mountProductHeader(..., {selfId, openTarget})` übergibt an `openTarget` ausschließlich
eine der fünf Katalog-IDs. Der Host liefert `opened`, `focused`, `missing`, `failed`
oder `uncertain`. Native Hosts dürfen nur ihren eigenen PID mit festem argv an
`~/.local/bin/kirabridge --principal local family switch TARGET --source-pid PID`
übergeben; Pfade, PID, argv oder URLs kommen nicht aus dem Browser. Der Broker
prüft Installation, Caller, Startidentität und tatsächlichen Fenstereffekt.
Erfolg erfordert Exit 0 und top-level JSON `{"success":true,"active_product":"TARGET",
"actual_outer_bounds":{"x":0,"y":0,"width":1360,"height":780},"visible_family_windows":1}`
mit endlichen Zahlen und positiven Abmessungen. Fehler liefern Exit ungleich 0,
`success:false`, `error:{code,message}` und `execution_outcome_unknown:boolean`.
Fehler/unklare JSON-Antworten sind kein Erfolg, kein Navigieren oder Blind-Replay.
Der bisherige HTTP-Adapter bleibt für ausdrücklich konfigurierte Browserziele
bestehen; er belegt keinen nativen Fenstermodus.

Native Fünferintegration und installierte Laufzeit sind separat abzunehmen.

## Öffentliche API

ES-Module, ohne React/DOM-Bibliothek:

```js
import { mountAppBar } from "./networkpunkt-appbar.js";
const bar = mountAppBar(reservedElement, {
  catalog, locale: "de", peers: trustedExpectedBindings,
  colors: trustedNamedToolColors, // {appId:{value:"#RRGGBB",sourceRef:"belegter-Token"}}
  onOpen: allowedHostOpenAdapter
});
const ticket = bar.begin("4allpass");
// Erst nach Prüfung durch den vorhandenen authentisierten Hostadapter:
bar.receive("4allpass", ticket, verifiedMetadata);
// Alternativ bar.fail(appId, ticket, "error" oder "unknown").
// bar.reset(appId, newTrustedExpectedBinding) invalidiert alte Instanz/Generation.
// bar.setLocale("en"); bar.destroy();
```

Kein Netzwerk, Storage, PID-/Portscan, allgemeiner Shellaufruf, Fensteröffnen
oder fachlicher Auftrag im Renderer. `clock`/`wallClock` sind injizierbare lokale
Fixtureuhren; normale Hosts verwenden performance.now und Date.now.

## Statusadaptervertrag

Erwartete Bindung aus vertrauenswürdiger lokaler Installation:

```
{appId, connectionRef, peerRef, peerEpoch,
 unlockScope?: {userRef, vaultRef}}
```

`peerRef` muss das erwartete Gegenüber des vorhandenen authentisierten Kanals
bezeichnen, `peerEpoch` dessen bestätigte Instanz. Öffentliche IDs/Fingerprints
allein authentisieren nichts. Insbesondere darf der Adapter weder PID,
Transport-live, erfolgreichen Start noch health200 in `confirmed` übersetzen.
Wo der Kanal fehlt, bleibt der Status unknown. Ein frei gepostetes
`authenticated:true` ist kein Beweis und kein Feld dieses Vertrags.

Verifizierte, geheimnisfreie Metadaten aus diesem Adapter:

```
{v:1, appId, connectionRef, peerRef, peerEpoch, seq,
 state:"confirmed"|"connecting"|"disconnected"|"unknown"|"error",
 ttlMs:1..15000,
 vault?: {userRef,vaultRef,allowed:true,
          state:"locked"|"unlocked"|"unknown",ttlMs:1..connectionTTL}}
```

Der Renderer prüft Form/Zuordnung/Frische, **nicht** Authentisierung oder
Gerätebesitz. Der Hostadapter muss die echte Antwort an die angefragte
Verbindung und aktuelle erlaubte Nutzer-/Tresorzuordnung binden. Ein Boolean
ersetzt diese Prüfung nicht. Keine neuen Schlüssel, Secrets, Konten oder
Berechtigungen für die Darstellung. Keine Tresorobjekte, Inhalte, Tokens,
Passwörter, Grants, Budgets oder Aktivitätsdaten in diesem DTO.

Eine fehlende Toolfarbe muss aus dokumentierter Gestaltung kommen, benannt
durch den vertrauenswürdigen lokalen Hostadapter (`colors` mit sourceRef).
Statusantworten dürfen sie nicht liefern. Ohne diese Konfiguration bleibt die
Anzeige neutral; die Browserfixture verwendet ausdrücklich eine synthetische
Testfarbe, keine freigegebene AP4-Marke.

Pro Peer höchstens ein laufender lokaler Check; `begin` liefert dafür ein
unveränderliches lokales Ticket, kein Auth-/Netzprotokoll. Deadline2s; TTL maximal
15s und konservativ ab lokalem Checkbeginn, nicht ab einer verspäteten Antwort.
Der Host begrenzt seine tatsächlichen Abfragen auf vorhandenen4s- oder5s-Takt;
der reine Renderer fragt nichts ab. Gleiche/alte Sequenzen, falsche App/Verbindung/
Peer/Instanz, fremde Tickets, Zeitüberschreitung und ungültige Metadaten werden
verworfen. Reset/Verstecken/pagehide invalidieren die Generation. Lokale monotone
und Wanduhr werden gemeinsam konservativ bewertet; Schlaf oder Uhr-Rücksprung
darf kein altes Grün verlängern. Das je Vorgang beobachtete Alter sinkt nie;
ein beobachteter Rücksprung einer der beiden Uhren macht dessen Lease dauerhaft
ungültig, auch wenn die Uhr noch nach dem ursprünglichen Checkbeginn liegt.
Erst ein neuer Check kann wieder bestätigen. Es wird kein Status aus Storage restauriert.

`confirmed` mit gültiger Verbindung erzeugt den ruhigen eigenen Ring. Nur AP4
mit explizitem allowed:true und exakt erwartetem userRef/vaultRef darf zusätzlich
unlocked anzeigen. Eigene kürzere Vault-TTL endet ohne falsches locked; der
Verbindungsring darf dabei ruhig weiterleuchten. Locked ist ausdrücklich
gesperrt, unknown ausdrücklich unbekannt. Andere Apps erhalten niemals einen
Aktivitäts-/Unlockpuls. Ein fehlgeschlagener Check neutralisiert sofort.

## Fester Öffnungsadapter

`onOpen({appId,actionId,signal})` erhält nur feste Katalog-ID, lokalen Vorgangsbezug
und Abbruchsignal. Kein freies Ziel/Argument aus Projekt-/Thread-/Teamdaten.
Der Host mappt diese ID auf bereits erlaubtes festes Ziel und schützt Fokus/
Start sowie begrenzte Idempotenz selbst. Antwort:
`{actionId,outcome:"focused"|"opened"|"failed"|"unknown"}`.

Parallel-/Doppelklicks werden zusammengeführt (mindestens600ms). Deadline2s
mit derselben konservativen monotonen/Wanduhrmessung wie beim Status: Schlaf,
Wanduhrfortschritt bei stehender monotoner Uhr oder beobachteter Rücksprung
können einen verspäteten Erfolg nicht nachträglich akzeptieren;
unklarer Ausgang bleibt gegen weiteren Start gesperrt und hat keinen
automatischen Retry. Erst nach eigener Zielprüfung darf der Host
`clearOpen(appId)` aufrufen. Ein ungültiger Uhrwert erfüllt niemals die
600ms-Mindestwartezeit. Ein Rücksprung während dieser Wartezeit sperrt auch
nach einem sofortigen opened-Ergebnis; nach Hostprüfung beginnt eine neue volle
600ms-Wartezeit. Erst ein endliches geprüftes Alter darf die Wartezeit beenden.
Späte Ergebnisse ersetzen keinen neueren Vorgang.
Destroy signalisiert Abbruch; ein unkooperativer Adapter kann nicht vom
Renderer zwangsweise beendet werden, verändert aber dessen DOM nicht mehr.
Fehlendes Ziel/Fehler führen zu festen DE/EN-Handlungen, nie rohen Responses.
Ein Öffnungserfolg bestätigt **niemals** eine Verbindung oder Tresorfreigabe.

## Geprüfter und weiterhin offener Umfang

`python -m pytest -q tests/test_appbar.py tests/test_ui_assets.py` führt die
35 reinen Node-Zustandsprüfungen sowie echtes Chromium-DOM/CSS aus. Die
Browserfixture liefert nur freigegebene lokale Assets über abgefangene
Fixture-Requests; keine echte App, Verbindung, Konten, Datenbank oder Startziele.
DE/EN/Keyboard, Scope/TTL/Fehler/Wiederverbindung, Ring-/Bildgeometrie, reduzierte
Bewegung, Timerabbau und keine doppelten synthetischen Starts werden gemessen.
Das ist Renderer-/Accessibility-Verhalten, keine vollständige Screenreader-,
Nutzer-, Native- oder Verbundabnahme. Keine Vorlage wird produktiv importiert.

Offen bleiben KiraBridge-Asset, belegter AP4-Ringfarbwert, erste KB-Einbindung, abgesicherte echte
Öffnungs-/Statusadapter, danach TD/AP-Mounts und jeweilige native/Host-Abnahme.
Ein neuer Adapter erweitert nicht Tresor-, Projekt- oder Auftragsrechte.
