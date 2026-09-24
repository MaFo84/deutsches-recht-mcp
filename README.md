# Deutsches Recht MCP-Server

MCP-Connector für Claude, der Gesetzestexte und Rechtsprechung über offizielle und offene Schnittstellen bereitstellt. Kein Scraping, keine lizenzpflichtigen Datenbanken.

| Quelle | Inhalt | Zugang |
|---|---|---|
| NeuRIS (rechtsinformationen.bund.de, Testphase) | Bundesgesetze und -verordnungen, Entscheidungen von BVerfG, BGH, BVerwG, BFH, BAG, BSG | öffentlich, ohne API-Key |
| Open Legal Data (de.openlegaldata.io) | Entscheidungen aller Instanzen (unvollständig), Zitationsgraph Norm → Urteile | öffentlich, Token optional |

## Tools

| Tool | Zweck |
|---|---|
| `norm_abrufen` | Wortlaut einer Norm in der geltenden Fassung, optional nur ein Absatz (z.B. InsO, § 26, Abs. 4) |
| `gesetz_suchen` | Suche nach Gesetzen und Verordnungen |
| `rechtsprechung_suchen` | Volltextsuche in Entscheidungen, beide Quellen, Filter nach Gericht und Datum |
| `entscheidung_abrufen` | Metadaten und Volltext einer Entscheidung (`neuris:…` oder `oldp:…`) |
| `rechtsprechung_zu_norm` | Entscheidungen, die eine Norm zitieren, plus Volltexttreffer der Bundesgerichte |
| `zitierende_entscheidungen` | Entscheidungen, die eine Entscheidung zitieren (Open Legal Data) |
| `verweise_einer_entscheidung` | Normen und Urteile, auf die eine Entscheidung verweist (Open Legal Data) |
| `quellenstatus` | Erreichbarkeit beider Quellen |

Alle Tools sind rein lesend. Jede Antwort enthält Quelle, URL und einen Verifikationshinweis.

## Deployment

Der Server ist ein Docker-Container mit HTTPS-Endpunkt (Streamable HTTP). Der Endpunkt lautet `https://<host>/<MCP_PATH_SECRET>/mcp`, der Health-Check `https://<host>/health`.

### Variante A: Render (am einfachsten)

1. Auf render.com „New → Blueprint“ wählen und dieses Repository (https://github.com/MaFo84/deutsches-recht-mcp) verbinden. `render.yaml` legt den Dienst in Frankfurt an und erzeugt `MCP_PATH_SECRET` automatisch.
2. Nach dem Deploy unter „Environment“ den Wert von `MCP_PATH_SECRET` kopieren.

Kosten: Plan „Starter“, ca. 7 USD pro Monat.

### Variante B: Azure Container Apps

```bash
az group create -n rg-recht-mcp -l germanywestcentral
az acr create -n fostecrechtmcp -g rg-recht-mcp --sku Basic --admin-enabled true
az acr build -r fostecrechtmcp -t deutsches-recht-mcp:1.0 .
az containerapp up -n deutsches-recht-mcp -g rg-recht-mcp \
  --image fostecrechtmcp.azurecr.io/deutsches-recht-mcp:1.0 \
  --ingress external --target-port 8000 \
  --env-vars MCP_PATH_SECRET=$(openssl rand -hex 24)
```

### Umgebungsvariablen

| Variable | Pflicht | Bedeutung |
|---|---|---|
| `MCP_PATH_SECRET` | empfohlen | langer Zufallswert, wird Teil der URL; schützt vor Fremdnutzung |
| `MCP_BEARER_TOKEN` | nein | zusätzlicher Bearer-Token für Clients, die Header setzen können (nicht für den Claude Custom Connector) |
| `ALLOWED_HOSTS` | nein | erlaubte Host-Header (DNS-Rebinding-Schutz), z.B. `recht.fostec.com` |
| `OLDP_API_TOKEN` | nein | Token für Open Legal Data, falls künftig verlangt |
| `PORT` | nein | Standard 8000 |

## Einbindung in Claude

1. Claude öffnen → Einstellungen → Connectors → „Custom Connector hinzufügen“.
2. Name: `Deutsches Recht`, URL: `https://<host>/<MCP_PATH_SECRET>/mcp`. Keine Authentifizierung auswählen.
3. In Team- oder Enterprise-Organisationen fügt ein Owner den Connector unter den Organisationseinstellungen hinzu; danach aktivieren ihn die Nutzer für sich.
4. Im Chat bzw. in Cowork den Connector für die Unterhaltung einschalten.

Die URL mit dem Pfad-Secret wie ein Passwort behandeln. Die Daten sind öffentlich, das Secret verhindert aber, dass Dritte den Server auf Kosten von FOSTEC & Company nutzen.

## Abnahmetest nach dem Deploy (wichtig)

Die Antwortformate der Schnittstellen wurden aus der offiziellen API-Beschreibung und aus Open-Source-Implementierungen abgeleitet und mit simulierten Antworten getestet. Den Test gegen die echten Schnittstellen führt folgendes Skript durch:

```bash
pip install "mcp>=1.9,<2"
python smoke_test.py https://<host>/<MCP_PATH_SECRET>/mcp
```

Erwartet: 6/6 Prüfungen ohne Fehler. Schlägt eine Prüfung fehl, Ausgabe an den Entwickler bzw. an Claude geben; die Anpassung betrifft dann in der Regel nur ein Feld in `neuris.py` oder `oldp.py`.

## Lokal entwickeln und testen

```bash
pip install -e ".[test]"
pytest -q                                   # 13 Tests, ohne Netzzugriff
MCP_PATH_SECRET=dev deutsches-recht-mcp      # Server auf http://localhost:8000/dev/mcp
```

## Grenzen

- NeuRIS ist in der Testphase; Schnittstelle und Datenbestand können sich ändern, Bundesgerichte erst ab ca. 2010.
- Open Legal Data ist unvollständig, insbesondere bei Amts- und Landgerichten. Fehlende Treffer beweisen nicht, dass es keine Rechtsprechung gibt.
- Landesrecht ist über NeuRIS nicht abgedeckt.
- Ergebnisse sind Arbeitsgrundlage. Zitate vor Verwendung in Schriftsätzen am amtlichen Text verifizieren.

## Rechtliches

Gesetze und Gerichtsentscheidungen sind amtliche Werke und gemeinfrei (§ 5 UrhG). Genutzt werden ausschließlich die dafür vorgesehenen öffentlichen Schnittstellen. Der User-Agent verweist auf dieses Repository; über `USER_AGENT` kann eine eigene Kontaktangabe gesetzt werden. Vor produktiver Nutzung empfiehlt sich eine kurze Bestätigung der Nutzungsbedingungen von Open Legal Data per E-Mail.
