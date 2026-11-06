"""Project memory copy for the existing German/English interface."""

PROJECT_MEMORY_STRINGS = {
    "project.memory.nav": {"de": "Projekte", "en": "Projects"},
    "project.memory.title": {"de": "Projektgedächtnis", "en": "Project memory"},
    "project.memory.lead": {
        "de": "Gespeicherter Stand, nächste Schritte und offene Fragen. Berichte und Quellen sind noch zu prüfen.",
        "en": "Saved context, next steps and open questions. Reports and sources still need review.",
    },
    "project.memory.select": {"de": "Projekt", "en": "Project"},
    "project.memory.choose": {"de": "Projekt auswählen", "en": "Choose a project"},
    "project.memory.archived": {
        "de": "Archivierte Threads einbeziehen",
        "en": "Include archived threads",
    },
    "project.memory.open": {"de": "Stand anzeigen", "en": "Show context"},
    "project.memory.no_projects": {
        "de": "Noch kein Projekt vorhanden. Starte mit deiner Idee ein neues Projekt.",
        "en": "No projects yet. Start a new project with your idea.",
    },
    "project.memory.empty": {
        "de": "Diesem Projekt sind noch keine Threads ausdrücklich zugeordnet.",
        "en": "No threads have been explicitly assigned to this project yet.",
    },
    "project.memory.count": {
        "de": "{shown} von {total} zugeordneten Threads auf dieser Seite",
        "en": "{shown} of {total} assigned threads on this page",
    },
    "project.memory.excerpts": {
        "de": "Diese Übersicht zeigt Auszüge. Öffne einen Thread für den vollständigen Verlauf.",
        "en": "This overview shows excerpts. Open a thread for its full history.",
    },
    "project.memory.resume": {"de": "Wiedereinstieg", "en": "Resume context"},
    "project.memory.next": {"de": "Nächster Schritt:", "en": "Next step:"},
    "project.memory.no_reentry": {
        "de": "Noch kein Wiedereinstieg gespeichert.",
        "en": "No resume context saved yet.",
    },
    "project.memory.notes": {
        "de": "Gespeicherte Notizen – Auszug",
        "en": "Saved notes – excerpt",
    },
    "project.memory.knowledge": {
        "de": "Entscheidungen, Aufgaben und Fragen",
        "en": "Decisions, tasks and questions",
    },
    "project.memory.no_knowledge": {
        "de": "Keine Wissenseinträge im angezeigten Auszug.",
        "en": "No knowledge entries in this excerpt.",
    },
    "project.memory.source": {"de": "Quellenverweis:", "en": "Source reference:"},
    "project.memory.reports": {"de": "Letzte Beiträge", "en": "Recent contributions"},
    "project.memory.thread": {"de": "Thread öffnen", "en": "Open thread"},
    "project.memory.more": {"de": "Weitere Threads", "en": "More threads"},
    "project.memory.changed": {
        "de": "Der Projektstand hat sich geändert. Mit „Stand anzeigen“ die Übersicht neu laden.",
        "en": "The project has changed. Reload the overview with “Show context”.",
    },
    "project.memory.error": {
        "de": "Dieser Projektstand kann nicht angezeigt werden. Projekt auswählen und erneut anzeigen.",
        "en": "This project context cannot be displayed. Choose a project and show its context again.",
    },
    "project.start.title": {"de": "Neues Projekt", "en": "New project"},
    "project.start.lead": {
        "de": "Beschreibe deine Idee. Daraus entsteht ein erster Plan, den du anpassen kannst.",
        "en": "Describe your idea. Start with a first plan that you can adjust.",
    },
    "project.start.name": {
        "de": "Projektname (optional)",
        "en": "Project name (optional)",
    },
    "project.start.idea": {"de": "Deine Idee", "en": "Your idea"},
    "project.start.preview": {
        "de": "Ersten Plan vorbereiten",
        "en": "Prepare a first plan",
    },
    "project.start.outline": {
        "de": "Lokaler Ausgangsentwurf. Passe Ziele, nächste Schritte und offene Fragen an.",
        "en": "Local starting outline. Adjust goals, next steps and open questions.",
    },
    "project.start.goals": {"de": "Ziele", "en": "Goals"},
    "project.start.next_steps": {"de": "Nächste Schritte", "en": "Next steps"},
    "project.start.open_questions": {"de": "Offene Fragen", "en": "Open questions"},
    "project.start.lines": {
        "de": "Ein Eintrag pro Zeile, höchstens acht je Feld. Die Schritte werden als Ideen gespeichert.",
        "en": "One item per line, up to eight per field. Steps are saved as ideas.",
    },
    "project.start.save": {
        "de": "Projekt und Entwurf speichern",
        "en": "Save project and draft",
    },
    "project.start.check": {
        "de": "Gespeicherten Stand prüfen",
        "en": "Check saved state",
    },
    "project.start.error": {
        "de": "Der Entwurf wurde nicht bestätigt. Prüfe die Eingaben und verwende weiter dasselbe Formular.",
        "en": "The draft was not confirmed. Check your input and keep using this form.",
    },
    "project.start.uncertain": {
        "de": "Das Ergebnis ist noch unklar. Prüfe zuerst den gespeicherten Stand. Dieses Formular behält seine Kennung.",
        "en": "The outcome is still unclear. Check the saved state first. This form keeps its identifier.",
    },
    "project.start.not_confirmed": {
        "de": "Ein gespeichertes Projekt ist für dieses Formular noch nicht bestätigt. Der Entwurf auf der vorherigen Seite bleibt maßgeblich.",
        "en": "No saved project is confirmed for this form yet. Keep the draft on the previous page.",
    },
    "project.start.default.goals": {
        "de": "Gewünschten Nutzen und Erfolgskriterien festhalten",
        "en": "Define the intended benefit and success criteria",
    },
    "project.start.default.next_steps": {
        "de": "Anforderungen und vorhandene Quellen prüfen",
        "en": "Review requirements and existing sources",
    },
    "project.start.default.open_questions": {
        "de": "Was muss zuerst geklärt werden?",
        "en": "What needs to be clarified first?",
    },
}

PROJECT_MEMORY_STRINGS.update(
    {
        "project.plan.title": {
            "de": "Projektplan und Verlauf",
            "en": "Project plan and history",
        },
        "project.plan.lead": {
            "de": "Schreibe den Plan fort und halte fest, warum er sich ändert. Frühere Fassungen bleiben nachvollziehbar.",
            "en": "Update the plan and record why it changes. Earlier versions remain traceable.",
        },
        "project.plan.link": {
            "de": "Plan und Verlauf öffnen",
            "en": "Open plan and history",
        },
        "project.plan.current": {
            "de": "Aktueller Wiedereinstieg · Fassung {revision}",
            "en": "Current resume context · version {revision}",
        },
        "project.plan.version": {
            "de": "Fassung {revision}",
            "en": "Version {revision}",
        },
        "project.plan.history": {
            "de": "Bisherige Fassungen und Herkunft",
            "en": "Earlier versions and provenance",
        },
        "project.plan.more": {"de": "Ältere Fassungen", "en": "Older versions"},
        "project.plan.observed": {
            "de": "Beobachteter Ausgangsstand aus dem bisherigen Plan, kein ursprünglicher Erstellungsnachweis.",
            "en": "Observed baseline from the existing plan, not original creation evidence.",
        },
        "project.plan.frozen": {
            "de": "Gespeicherte frühere Fassung. Für Änderungen den aktuellen Plan öffnen.",
            "en": "Saved earlier version. Open the current plan to make changes.",
        },
        "project.plan.edit": {
            "de": "Aktuellen Plan fortschreiben",
            "en": "Update the current plan",
        },
        "project.plan.summary": {
            "de": "Zusammenfassung für den Wiedereinstieg",
            "en": "Summary for resuming work",
        },
        "project.plan.reason": {
            "de": "Warum ändert sich der Plan?",
            "en": "Why is the plan changing?",
        },
        "project.plan.save": {
            "de": "Neue Planfassung speichern",
            "en": "Save a new plan version",
        },
        "project.plan.reload": {
            "de": "Aktuellen Plan öffnen",
            "en": "Open the current plan",
        },
        "project.plan.no_open": {
            "de": "Kein offener Schritt in dieser Planfassung.",
            "en": "No open step in this plan version.",
        },
        "project.plan.source_hint": {
            "de": "Quellen sind referenziert, noch nicht extern geprüft. Gespeicherte Schritte starten keine Arbeit.",
            "en": "Sources are referenced and not externally verified. Saved steps do not start work.",
        },
        "project.plan.read_error": {
            "de": "Der aktuelle Planstand ist nicht verlässlich lesbar. Projektzuordnung und erhaltene Verlaufsbelege zuerst prüfen.",
            "en": "The current plan cannot be read reliably. Check project membership and retained history first.",
        },
        "project.plan.error": {
            "de": "Die neue Fassung wurde nicht bestätigt. Prüfe die Eingaben; der Entwurf bleibt in diesem Formular.",
            "en": "The new version was not confirmed. Check the input; this form keeps the draft.",
        },
        "project.plan.stale": {
            "de": "Plan, Wissen oder Projektzuordnung haben sich geändert. Öffne den aktuellen Plan und gleiche deinen Entwurf bewusst ab.",
            "en": "The plan, knowledge or project membership changed. Open the current plan and reconcile your draft.",
        },
        "project.plan.uncertain": {
            "de": "Der Ausgang ist unklar. Erst den gespeicherten Stand prüfen; dieses Formular behält seine Kennung und den Entwurf.",
            "en": "The outcome is unclear. Check the saved state first; this form keeps its identifier and draft.",
        },
    }
)
