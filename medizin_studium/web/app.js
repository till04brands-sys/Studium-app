"use strict";

/* Die Oberfläche rechnet nichts aus.
 *
 * Rückstand, Takt, Blockuhr, „im Blick" — das kommt fertig aus studium.py.
 * Hier steht nur, wie es aussieht, plus die Geometrie des Wochenrasters
 * (Minuten in Pixel), die nirgendwo sonst gebraucht wird.
 *
 * Zwei Regeln aus dem Vault gelten auch hier:
 * - Leer ist nicht null. Fehlt ein Wert, steht „unbekannt" da, kein 0.
 * - Vermutetes bleibt sichtbar vermutet — gestrichelt, mit „nicht amtlich".
 */

const WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"];

// Eine Stunde ist immer gleich hoch — nicht die Karte. Vorher war es
// umgekehrt: feste Gesamthöhe, und die Stunde wurde gestaucht, je weiter die
// Spanne reichte. Das hielt die Karte ruhig, kostete aber 812 Pixel auch in
// einer Woche, in der ab dem Nachmittag nichts mehr steht — mehr als eine
// Bildschirmhöhe für halb leeres Raster. Nebenbei ließen sich zwei Wochen
// nicht vergleichen, weil dieselbe Stunde mal höher und mal flacher war.
const STUNDE_HOEHE = 52;
// Deckel für Ausreißerwochen: Ab hier wird doch gestaucht, sonst schiebt ein
// einzelner Termin um 6:00 die halbe Startseite nach unten.
const RASTER_MAX = 660;
// So viele Stunden stehen gleichzeitig im Bild. Der Rest ist nicht weg,
// sondern gescrollt — auf der Startseite zählt der Überblick, und ein Raster
// über eine ganze Bildschirmhöhe ist keiner.
const SICHT_STUNDEN = 8;
// Grundraster. Es wächst nach den Daten, schrumpft aber nicht darunter —
// sonst springt die Höhe der Karte bei jedem Wochenwechsel.
const STUNDE_VON_VORGABE = 8;
const STUNDE_BIS_VORGABE = 18;

const zustand = {
  seite: "heute",
  tag: null,          // null = heute
  sicht: "woche",
  nurStudium: false,
  daten: null,        // /api/zustand
  block: null,        // /api/block
  orga: null,         // /api/orga
  eingang: null,      // /api/eingang
  einstellungen: null,
  laedt: false,
};

/* ------------------------------------------------------------- Werkzeug --- */

function el(name, klasse, text) {
  const knoten = document.createElement(name);
  if (klasse) knoten.className = klasse;
  if (text !== undefined && text !== null) knoten.textContent = String(text);
  return knoten;
}

function leeren(knoten) { while (knoten.firstChild) knoten.removeChild(knoten.firstChild); }

function minuten(hhmm) {
  if (!hhmm) return null;
  const [s, m] = hhmm.split(":");
  return Number(s) * 60 + Number(m);
}

function alsDatum(iso) { const [j, m, t] = iso.split("-").map(Number); return new Date(j, m - 1, t); }
function alsIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function plusTage(iso, n) { const d = alsDatum(iso); d.setDate(d.getDate() + n); return alsIso(d); }

function langesDatum(iso) {
  const d = alsDatum(iso);
  return `${WOCHENTAGE[(d.getDay() + 6) % 7]}, ${d.getDate()}. ${MONATE[d.getMonth()]} ${d.getFullYear()}`;
}

function tageWort(n) { return n === 1 ? "1 Tag" : `${n} Tage`; }
function tagenWort(n) { return n === 1 ? "einem Tag" : `${n} Tagen`; }

/* --------------------------------------------------------------- Laden --- */

async function holen(weg) {
  const antwort = await fetch(weg + (zustand.tag ? `?tag=${zustand.tag}` : ""), { cache: "no-store" });
  if (!antwort.ok) throw new Error(`Server antwortet mit ${antwort.status}`);
  return antwort.json();
}

async function laden() {
  if (zustand.laedt) return;
  zustand.laedt = true;
  // Ohne sichtbares Zeichen sieht eine langsame Google-Antwort wie eine
  // eingefrorene Seite aus.
  document.body.dataset.laedt = "ja";
  try {
    // „Heute" braucht Google und ist die teurere Anfrage; „Block" liest nur
    // den Vault. Deshalb wird nur geholt, was die sichtbare Seite braucht.
    if (zustand.seite === "block") zustand.block = await holen("/api/block");
    else if (zustand.seite === "orga") zustand.orga = await holen("/api/orga");
    else if (zustand.seite === "eingang") zustand.eingang = await holen("/api/eingang");
    else if (zustand.seite === "einstellungen") zustand.einstellungen = await holen("/api/einstellungen");
    else zustand.daten = await holen("/api/zustand");
    zeichnen();
  } catch (fehler) {
    zeigeMeldung("Der Server antwortet nicht", String(fehler.message || fehler), true);
  } finally {
    zustand.laedt = false;
    delete document.body.dataset.laedt;
  }
}

function zeigeMeldung(titel, text, istFehler) {
  const kasten = el("div", "meldung" + (istFehler ? " fehler" : ""));
  kasten.append(el("b", null, titel), el("p", null, text));
  document.getElementById("meldungen").append(kasten);
}

/* ------------------------------------------------------------ Zeichnen --- */

function zeichnen() {
  leeren(document.getElementById("meldungen"));
  // Eine Rückmeldung zu einer gerade getroffenen Entscheidung muss den
  // Neuaufbau überleben — sonst blitzt sie auf und ist weg, bevor man liest.
  if (zustand.hinweis) {
    const h = zustand.hinweis;
    zustand.hinweis = null;
    zeigeMeldung(h.titel, h.text, h.fehler);
  }
  for (const [id, name] of [["seiteHeute", "heute"], ["seiteBlock", "block"],
                            ["seiteOrga", "orga"], ["seiteEingang", "eingang"],
                            ["seiteEinstellungen", "einstellungen"]]) {
    document.getElementById(id).hidden = zustand.seite !== name;
  }
  // Die Wochennavigation gehört zum Kalender. Auf den anderen Seiten wäre sie
  // ein Knopf, der sichtbar nichts tut.
  for (const id of ["wocheZurueck", "wocheHeute", "wocheVor"]) {
    document.getElementById(id).hidden = zustand.seite !== "heute";
  }
  if (zustand.eingang) plaketteSetzen(zustand.eingang.offen);

  if (zustand.seite !== "heute") {
    if (zustand.seite === "block" && zustand.block) blockZeichnen(zustand.block);
    if (zustand.seite === "orga" && zustand.orga) orgaZeichnen(zustand.orga);
    if (zustand.seite === "eingang" && zustand.eingang) eingangZeichnen(zustand.eingang);
    if (zustand.seite === "einstellungen" && zustand.einstellungen) einstellungenZeichnen(zustand.einstellungen);
    if (zustand.daten) kopfZeichnen(zustand.daten);
    maengelZeichnen(zustand[zustand.seite === "block" ? "block" : zustand.seite]);
    return;
  }
  const d = zustand.daten;
  maengelZeichnen(d);
  kopfZeichnen(d);
  rasterZeichnen(d);
  ohneZeitZeichnen(d);
  jetztZeichnen(d);
  aufgabenZeichnen(d);
  ankiZeichnen(d);
  imBlickZeichnen(d);
  faecherZeichnen(d);
  hinweiseZeichnen(d);
}

function kopfZeichnen(d) {
  document.getElementById("bandDatum").textContent = langesDatum(d.heute);

  const block = d.block;
  document.getElementById("bandBlock").textContent = block
    ? `Woche ${block.woche} von ${block.wochen_gesamt} · ${block.phase}`
    : "kein Block erfasst";

  const klausur = document.getElementById("bandKlausur");
  if (!block || block.tage_bis_klausur === null || block.tage_bis_klausur === undefined) {
    klausur.textContent = "unbekannt";
    klausur.classList.add("leise");
  } else {
    klausur.textContent = tageWort(block.tage_bis_klausur) + (block.platzhalter ? " (nicht amtlich)" : "");
    klausur.classList.toggle("leise", Boolean(block.platzhalter));
  }

  const naechster = d.naechster;
  document.getElementById("bandNaechster").textContent = naechster
    ? `${naechster.von} ${naechster.titel}`
    : "nichts erfasst";

  const knopf = document.getElementById("bandAbgleich");
  const g = d.google || {};
  const beschriftung = {
    ok: g.aus_speicher ? "Google · aus dem Zwischenspeicher" : "Google · aktuell",
    nicht_eingerichtet: "Google nicht verbunden",
    fehler: "Google nicht erreichbar",
    aus: "Google ausgeblendet",
  };
  knopf.textContent = beschriftung[g.stand] || "Google · unbekannt";
  knopf.classList.toggle("warnung", g.stand === "fehler");

  const montag = d.woche_ab;
  const sonntag = plusTage(montag, 6);
  const a = alsDatum(montag), b = alsDatum(sonntag);
  document.getElementById("kalTitel").textContent = zustand.sicht === "tag"
    ? langesDatum(d.heute)
    : `${a.getDate()}.–${b.getDate()}. ${MONATE[b.getMonth()]} ${b.getFullYear()}`;
}

/* --- Wochenraster --- */

function sichtbareTermine(d) {
  return d.termine.filter((t) => !(zustand.nurStudium && t.bereich !== "studium"));
}

function rasterZeichnen(d) {
  const ziel = document.getElementById("raster");
  leeren(ziel);

  const alle = sichtbareTermine(d);
  if (!alle.length) {
    // Zwei verschiedene Leeren, und sie dürfen nicht gleich aussehen: nichts
    // erfasst ist ein Datenzustand, weggefiltert ist eine Einstellung.
    const leer = el("div", "raster-leer");
    if (d.termine.length) {
      leer.append(
        el("h2", null, "Keine Studientermine diese Woche"),
        el("p", null, `„Nur Studium“ blendet ${d.termine.length} andere Termine aus.`),
      );
      const knopf = el("button", "filter", "Filter aufheben");
      knopf.addEventListener("click", () => document.getElementById("nurStudium").click());
      leer.append(knopf);
    } else {
      leer.append(
        el("h2", null, "Stundenplan fehlt"),
        el("p", null, "Es ist nichts importiert — das heißt nicht „keine Termine“, sondern „nicht gemessen“."),
      );
    }
    ziel.append(leer);
    return;
  }

  const tage = [];
  const anzahl = zustand.sicht === "tag" ? 1 : 7;
  const start = zustand.sicht === "tag" ? d.heute : d.woche_ab;
  for (let i = 0; i < anzahl; i++) tage.push(plusTage(start, i));

  const jeTag = new Map(tage.map((t) => [t, { zeit: [], ganz: [] }]));
  for (const t of alle) {
    const fach = jeTag.get(t.tag);
    if (!fach) continue;
    (t.von ? fach.zeit : fach.ganz).push(t);
  }

  // Grenzen aus den Daten, nicht geraten: ein Termin um 6:15 darf nicht
  // oben abgeschnitten werden, nur weil das Raster bei 7 anfängt.
  let von = STUNDE_VON_VORGABE * 60, bis = STUNDE_BIS_VORGABE * 60;
  for (const t of alle) {
    if (!t.von) continue;
    von = Math.min(von, Math.floor(minuten(t.von) / 60) * 60);
    const ende = t.bis ? minuten(t.bis) : minuten(t.von) + 60;
    bis = Math.max(bis, Math.ceil(ende / 60) * 60);
  }
  const spanne = bis - von;
  const hoehe = Math.min(RASTER_MAX, (spanne / 60) * STUNDE_HOEHE);
  const proMinute = hoehe / spanne;
  const spalten = `repeat(${anzahl}, minmax(0, 1fr))`;
  // Die Stundenlinien im Hintergrund müssen exakt auf den Beschriftungen
  // sitzen. Ein fester Wert im Stylesheet driftet, sobald sich die Spanne
  // ändert — und sie ändert sich, sobald ein Termin aus dem Raster fällt.
  // Aus demselben Grund steht die Gesamthöhe hier und nicht im Stylesheet:
  // Zwei Stellen mit derselben Zahl laufen irgendwann auseinander, und dann
  // sitzen die Linien schief, ohne dass jemand einen Fehler sieht.
  ziel.style.setProperty("--stunde-hoehe", `${60 * proMinute}px`);
  ziel.style.setProperty("--raster-hoehe", `${hoehe}px`);

  // Kopfzeile
  const kopf = el("div", "netz-kopf");
  kopf.append(el("div"));
  const kopfTage = el("div", "netz-tage");
  kopfTage.style.gridTemplateColumns = spalten;
  tage.forEach((iso, i) => {
    const z = el("div", "tag-kopf" + (iso === d.heute ? " heute" : ""));
    const datum = alsDatum(iso);
    z.append(
      el("span", "tag-name", zustand.sicht === "tag" ? WOCHENTAGE[(datum.getDay() + 6) % 7] : KURZ[i]),
      el("span", "tag-datum", `${datum.getDate()}.${datum.getMonth() + 1}.`),
    );
    kopfTage.append(z);
  });
  kopf.append(kopfTage);
  ziel.append(kopf);

  // Ganztägiges
  if ([...jeTag.values()].some((f) => f.ganz.length)) {
    const streifen = el("div", "netz-kopf");
    streifen.append(el("div"));
    const spalte = el("div", "netz-tage");
    spalte.style.gridTemplateColumns = spalten;
    tage.forEach((iso) => {
      const zelle = el("div", "tag-kopf");
      for (const t of jeTag.get(iso).ganz) {
        const k = el("div", terminKlassen(t));
        k.style.position = "static";
        k.append(el("div", "t-titel", t.titel));
        zelle.append(k);
      }
      spalte.append(zelle);
    });
    streifen.append(spalte);
    ziel.append(streifen);
  }

  // Körper
  const koerper = el("div", "netz-koerper");
  const leiste = el("div", "stundenleiste");
  for (let m = von; m <= bis; m += 60) {
    const marke = el("div", "stunde", `${String(m / 60).padStart(2, "0")}:00`);
    marke.style.top = `${(m - von) * proMinute}px`;
    leiste.append(marke);
  }
  koerper.append(leiste);

  const netz = el("div", "netz-spalten");
  netz.style.gridTemplateColumns = spalten;
  tage.forEach((iso) => {
    const spalte = el("div", "tag-spalte" + (iso === d.heute ? " heute" : ""));

    if (iso === d.heute && d.jetzt) {
      const jetztMin = minuten(d.jetzt);
      if (jetztMin >= von && jetztMin <= bis) {
        const linie = el("div", "jetzt-linie");
        linie.style.top = `${(jetztMin - von) * proMinute}px`;
        linie.title = `jetzt · ${d.jetzt}`;
        spalte.append(linie);
      }
    }

    for (const t of legen(jeTag.get(iso).zeit)) {
      const beginn = minuten(t.von);
      const ende = t.bis ? minuten(t.bis) : beginn + 60;
      const kasten = el("div", terminKlassen(t));
      kasten.style.top = `${(beginn - von) * proMinute}px`;
      kasten.style.height = `${Math.max(18, (ende - beginn) * proMinute - 2)}px`;
      kasten.style.left = `calc(${t._spur * t._spuren * 0}% + ${3 + t._spur * (94 / t._spuren)}%)`;
      kasten.style.width = `calc(${94 / t._spuren}% - 4px)`;
      kasten.style.right = "auto";
      kasten.append(el("div", "t-titel", t.titel));
      const meta = [t.von && t.bis ? `${t.von}–${t.bis}` : t.von, t.ort].filter(Boolean).join(" · ");
      if (meta) kasten.append(el("div", "t-meta", meta));
      kasten.title = [t.titel, meta, t.quelle === "google" ? "aus Google" : null,
                      t.platzhalter ? "nicht amtlich" : null].filter(Boolean).join("\n");
      spalte.append(kasten);
    }
    netz.append(spalte);
  });
  koerper.append(netz);
  ziel.append(koerper);

  // Der Ausschnitt zeigt SICHT_STUNDEN Stunden, gescrollt wird der Rest.
  // Abschneiden käme nicht in Frage: Till arbeitet bis 20 Uhr, und ein
  // Termin, den das Raster nicht mehr hergibt, wäre auf dieser Seite
  // unsichtbar — nicht „später", sondern weg.
  const sicht = Math.min(hoehe, SICHT_STUNDEN * 60 * proMinute);
  koerper.style.maxHeight = `${sicht}px`;
  // Oben anfangen, wo der Tag anfängt: beim frühesten Termin, nicht bei der
  // ersten Rasterstunde. Sonst sieht man beim Öffnen leere Zeilen und muss
  // erst scrollen, um das zu finden, wonach man gesehen hat.
  const frueheste = alle.reduce(
    (m, t) => (t.von ? Math.min(m, minuten(t.von)) : m), bis);
  if (frueheste < bis) {
    koerper.scrollTop = Math.max(0, (frueheste - von) * proMinute - 8);
  }
}

function terminKlassen(t) {
  const klassen = ["termin", `bereich-${t.bereich || "extern"}`];
  if (t.platzhalter) klassen.push("platzhalter");
  if (t.status === "entfaellt") klassen.push("gestrichen");
  if (t.status === "fehler" || t.art === "fehler") klassen.push("fehler");
  return klassen.join(" ");
}

/* Überschneidungen nebeneinander legen, statt sie übereinander zu stapeln.
   Ohne das verdeckt „Till Arbeit" jede Vorlesung, die parallel läuft. */
function legen(liste) {
  const sortiert = [...liste].sort((a, b) => minuten(a.von) - minuten(b.von));
  const gruppen = [];
  let aktuell = [], bisher = -1;
  for (const t of sortiert) {
    const beginn = minuten(t.von);
    const ende = t.bis ? minuten(t.bis) : beginn + 60;
    if (aktuell.length && beginn >= bisher) { gruppen.push(aktuell); aktuell = []; bisher = -1; }
    aktuell.push(t);
    bisher = Math.max(bisher, ende);
  }
  if (aktuell.length) gruppen.push(aktuell);

  for (const gruppe of gruppen) {
    const spuren = [];
    for (const t of gruppe) {
      const beginn = minuten(t.von);
      let index = spuren.findIndex((ende) => ende <= beginn);
      if (index === -1) { index = spuren.length; spuren.push(0); }
      spuren[index] = t.bis ? minuten(t.bis) : beginn + 60;
      t._spur = index;
    }
    for (const t of gruppe) t._spuren = spuren.length;
  }
  return sortiert;
}

/* --- Ohne feste Zeit --- */

function ohneZeitZeichnen(d) {
  const ziel = document.getElementById("ohneZeit");
  leeren(ziel);
  if (!d.online || !d.online.length) {
    ziel.append(el("div", "karte-text", "Keine Online-Termine erfasst — unbekannt, nicht null."));
    return;
  }
  for (const o of d.online) {
    const zeile = el("div", "offen-zeile");
    zeile.append(
      el("span", "titel", o.titel || o.name || "(ohne Titel)"),
      el("span", "karte-notiz", o.frist || o.fach || ""),
    );
    ziel.append(zeile);
  }
}

/* --- Jetzt --- */

function jetztZeichnen(d) {
  const ziel = document.getElementById("jetzt");
  leeren(ziel);
  const n = d.naechster;
  if (!n) {
    const nichts = el("div", "nichts");
    nichts.append(document.createTextNode("Kein Termin bekannt."), el("br"),
                  el("small", null, "Das heißt: nichts erfasst — nicht „nichts los“."));
    ziel.append(nichts);
    return;
  }
  ziel.append(el("h2", null, n.titel));
  const zeile = el("div", "zeile");
  zeile.append(el("span", "uhr", n.bis ? `${n.von}–${n.bis}` : n.von));
  if (n.ort) zeile.append(el("span", null, n.ort));
  if (n.quelle === "google") zeile.append(el("span", null, "aus Google"));
  ziel.append(zeile);

  const zaehler = el("div", "zaehler");
  if (n.laeuft) {
    zaehler.append(el("b", null, "läuft"), el("span", null, "gerade"));
  } else if (n.tag !== d.heute) {
    zaehler.append(el("b", null, alsDatum(n.tag).getDate() + "."), el("span", null, "nicht heute"));
  } else {
    const stunden = Math.floor(n.minuten_bis / 60), rest = n.minuten_bis % 60;
    zaehler.append(el("b", null, stunden ? `${stunden}:${String(rest).padStart(2, "0")} h` : `${rest} min`),
                   el("span", null, "bis Beginn"));
  }
  ziel.append(zaehler);
}

/* --- Aufgaben --- */

function aufgabenZeichnen(d) {
  const ziel = document.getElementById("aufgaben");
  leeren(ziel);
  const kopf = document.getElementById("aufgabenKopf");
  const liste = d.aufgaben || [];
  kopf.textContent = liste.length ? `${liste.length} offen` : "nichts fällig";

  if (!liste.length) {
    ziel.append(el("div", "karte-text",
      "Keine Aufgaben fällig. Aufgaben entstehen aus Themen und Fristen — beides ist noch leer."));
    return;
  }

  const behaelter = el("div", "liste");
  for (const a of liste) {
    const zeile = el("div", "aufgabe");
    const kaestchen = el("button", "kaestchen", "✓");
    kaestchen.setAttribute("aria-checked", "false");
    kaestchen.setAttribute("aria-label", `„${a.titel}“ abhaken`);
    kaestchen.addEventListener("click", () => abhaken(a, kaestchen, zeile, true));

    const text = el("div", "text");
    text.append(el("div", "titel", a.titel));
    const unten = [a.fach, a.typ].filter(Boolean).join(" · ");
    if (unten) text.append(el("div", "fach", unten));

    const meta = el("span", "aufgabe-meta");
    meta.className = "meta" + (a.ueberfaellig > 0 ? " spaet" : "");
    meta.textContent = a.ueberfaellig > 0 ? `${a.ueberfaellig} T. über` : "heute";

    zeile.append(kaestchen, text, meta);
    behaelter.append(zeile);
  }
  ziel.append(behaelter);
}

/* Abhaken war eine Einbahnstraße: Die Aufgabe verschwand beim nächsten Laden,
   und ein Fehlklick war nur in Obsidian zu reparieren. Jetzt bleibt die Zeile
   stehen — durchgestrichen, mit einem Weg zurück. */
async function abhaken(aufgabe, kaestchen, zeile, erledigt = true) {
  kaestchen.disabled = true;
  try {
    const antwort = await fetch("/api/aufgabe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: aufgabe.id, erledigt, pruefsumme: aufgabe.pruefsumme }),
    });
    const ergebnis = await antwort.json();
    if (antwort.status === 409) {
      zeigeMeldung("Die Zeile hat sich geändert",
        "Obsidian oder Jarvis haben dieselbe Aufgabe angefasst. Nichts wurde überschrieben — bitte neu laden.", true);
      return;
    }
    if (!antwort.ok || ergebnis.fehler) throw new Error(ergebnis.fehler || antwort.status);

    // Beim Schreiben hat sich die Zeile geändert. Ohne die neue Prüfsumme
    // schlüge das Zurücknehmen sofort als Konflikt fehl.
    if (ergebnis.pruefsumme) aufgabe.pruefsumme = ergebnis.pruefsumme;
    kaestchen.setAttribute("aria-checked", String(erledigt));
    zeile.classList.toggle("erledigt", erledigt);
    zurueckKnopf(aufgabe, kaestchen, zeile, erledigt);
  } catch (fehler) {
    zeigeMeldung("Konnte nicht abhaken", String(fehler.message || fehler), true);
  } finally {
    kaestchen.disabled = false;
  }
}

function zurueckKnopf(aufgabe, kaestchen, zeile, erledigt) {
  const vorhanden = zeile.querySelector(".zurueck");
  if (vorhanden) vorhanden.remove();
  if (!erledigt) return;
  const knopf = el("button", "zurueck", "rückgängig");
  knopf.title = "Erledigt-Datum wieder entfernen";
  knopf.addEventListener("click", () => abhaken(aufgabe, kaestchen, zeile, false));
  zeile.querySelector(".meta").before(knopf);
}

/* --- Anki --- */

/* „Anki läuft nicht" wäre falsch, wenn AnkiConnect antwortet und nur die
   Sammlung zu ist. Beides heißt „Fälligkeit unbekannt", aber der Grund ist ein
   anderer — und nur einer davon wird durch Anki-Starten besser. */
function ankiUeberschrift(a) {
  return a.stand === "aus" ? "Anki läuft nicht" : "Anki antwortet, liefert aber nichts";
}

function ankiZeichnen(d) {
  const ziel = document.getElementById("anki");
  leeren(ziel);
  const a = d.anki || { stand: "aus" };

  if (a.stand !== "ok" && a.stand !== "leer") {
    const kasten = el("div", "warnkasten");
    kasten.append(el("b", null, ankiUeberschrift(a)),
                  el("span", null, `${a.text || "Keine Verbindung zu AnkiConnect."} ` +
                     "Fälligkeit ist unbekannt — ausdrücklich nicht „0 fällig“."));
    ziel.append(kasten);
    return;
  }
  if (a.stand === "leer") {
    ziel.append(el("div", "karte-text", a.text));
    return;
  }

  const koerper = el("div", "liste");
  const zahl = el("div", "anki-zahl");
  zahl.append(el("b", null, a.gesamt), el("span", null, "fällige Karten"));
  koerper.append(zahl);
  for (const zeile of a.faecher) {
    const z = el("div", "anki-zeile");
    z.append(el("span", "strich"), el("span", null, zeile.fach), el("span", "n", zeile.n));
    koerper.append(z);
  }
  ziel.append(koerper);
}

/* --- Im Blick --- */

function imBlickZeichnen(d) {
  const ziel = document.getElementById("imBlick");
  leeren(ziel);
  const liste = d.im_blick || [];
  if (!liste.length) {
    ziel.append(el("div", "karte-text",
      "Nichts im Blick — es gibt noch keine Daten, aus denen sich eine Folge ableiten ließe."));
    return;
  }
  const behaelter = el("div", "liste");
  for (const w of liste) {
    const zeile = el("div", "blick-zeile");
    zeile.append(el("span", "blick-marke" + (w.art === "frist" ? " hart" : ""),
                    w.art === "frist" ? "FRIST" : "RÜCKSTAND"));
    const text = el("div", "text-block");
    text.append(el("div", "text", w.titel), el("div", "folge", w.hinweis));
    zeile.append(text);
    behaelter.append(zeile);
  }
  ziel.append(behaelter);
}

/* --- Fächer --- */

const STUFEN = ["priming", "notizen", "feynman", "loci", "anki"];

function faecherZeichnen(d) {
  const ziel = document.getElementById("faecher");
  leeren(ziel);
  const liste = d.faecher || [];
  if (!liste.length) {
    ziel.append(el("div", "karte-text", "Keine Fächer erfasst."));
    return;
  }
  for (const f of liste) {
    const kachel = el("button", "kachel" + (f.platzhalter ? " platzhalter" : ""));
    kachel.title = f.platzhalter ? `${f.name} — nicht amtlich` : f.name;
    kachel.addEventListener("click", () => fachOeffnen(f.id, liste));

    const oben = el("div", "oben");
    oben.append(el("span", "strich"), el("span", "kurz", f.name),
                el("span", "ampel " + (f.ampel || "")));
    kachel.append(oben);

    const stufen = el("div", "stufen");
    for (const name of STUFEN) {
      const wert = (f.stufen || {})[name] || 0;
      const anteil = f.themen_gesamt ? wert / f.themen_gesamt : 0;
      stufen.append(el("span", "stufe" + (anteil >= 1 ? " voll" : anteil > 0 ? " teil" : "")));
    }
    kachel.append(stufen);

    kachel.append(el("div", "takt", f.hat_nenner
      ? (f.takt ? `${f.takt} Tage je Thema` : `${f.themen_gesamt} Themen`)
      : "Stoffliste fehlt"));
    ziel.append(kachel);
  }
}

/* --------------------------------------------------------- Seite Block --- */

function blockZeichnen(b) {
  blockKopfZeichnen(b);
  klausurenZeichnen(b);
  landebahnZeichnen(b);
  blockFaecherZeichnen(b);
  querZeichnen(b);
  ruhendZeichnen(b);
  if (b.block && b.block.platzhalter) {
    zeigeMeldung("Der Themenblock ist eine Vermutung",
      "Beginn, Ende und Klausurtermin stammen aus der Recherche, nicht aus einem Dokument der Fakultät.", false);
  }
}

function blockKopfZeichnen(b) {
  const uhr = b.block;
  document.getElementById("blockName").textContent = uhr ? uhr.name : "Kein Themenblock erfasst";
  // Vor dem ersten Tag wäre „Woche 1 von 9 · Tag 0" schlicht falsch — der
  // Block läuft dann noch gar nicht.
  document.getElementById("blockWoche").textContent = !uhr ? ""
    : uhr.tage_bis_beginn > 0
      ? `beginnt in ${tagenWort(uhr.tage_bis_beginn)}, am ${uhr.beginn}`
      : `Woche ${uhr.woche} von ${uhr.wochen_gesamt} · Tag ${uhr.tag} von ${uhr.tage_gesamt}`;

  const ziel = document.getElementById("blockPhasen");
  leeren(ziel);
  if (!uhr) return;

  const phasen = [
    { name: "vor Beginn", tage: null },
    { name: "Lehrbetrieb", tage: uhr.tage_lehrbetrieb },
    { name: "Endspurt", tage: uhr.tage_endspurt },
    { name: "Klausur", tage: null },
  ];
  const laufend = phasen.findIndex((p) => p.name === uhr.phase);
  phasen.forEach((p, i) => {
    const k = el("div", "phase" + (i === laufend ? " laeuft" : i < laufend ? " vorbei" : ""));
    k.append(el("div", "n", p.name),
             el("div", "t", p.tage === null || p.tage === undefined
               ? (i === laufend ? "jetzt" : "—")
               : `${p.tage} Tage`));
    ziel.append(k);
  });
}

function klausurenZeichnen(b) {
  const ziel = document.getElementById("klausuren");
  leeren(ziel);
  const uhr = b.block;

  const gross = el("div", "klausur-gross");
  gross.append(el("div", "marke",
    `BLOCKKLAUSUR · ${b.faecher.length} FÄCHER`));
  const zeile = el("div", "zahlzeile");
  if (uhr && uhr.tage_bis_klausur !== null && uhr.tage_bis_klausur !== undefined) {
    zeile.append(el("span", "zahl", uhr.tage_bis_klausur));
    const rechts = el("div");
    rechts.append(el("div", "wann", `Tage · ${uhr.klausur}`));
    if (uhr.tage_lehrbetrieb || uhr.tage_endspurt) {
      rechts.append(el("div", "teil",
        `${uhr.tage_lehrbetrieb} Tage Lehrbetrieb, danach ${uhr.tage_endspurt} Tage Endspurt`));
    }
    zeile.append(rechts);
  } else {
    zeile.append(el("span", "wann", "Kein Klausurtermin erfasst — unbekannt, nicht „keiner“."));
  }
  gross.append(zeile);
  gross.append(el("div", "regel",
    "Bestehen: ≥ 60 % hier und ≥ 60 % je Fach kumuliert über alle Blöcke."));
  ziel.append(gross);

  const eigene = b.eigene_klausuren || [];
  if (!eigene.length) {
    const kasten = el("div", "klausur-klein");
    kasten.append(el("div", "karte-marke", "EIGENER TERMIN"),
                  el("div", "hinweis", "Kein Fach mit eigener Klausur erfasst."));
    ziel.append(kasten);
    return;
  }
  for (const f of eigene) {
    const kasten = el("div", "klausur-klein");
    kasten.append(el("div", "karte-marke", "EIGENER TERMIN"), el("div", "fach", f.name));
    const zz = el("div", "zahlzeile");
    zz.append(el("span", "zahl", f.tage_bis_klausur !== null ? f.tage_bis_klausur : "?"),
              el("span", "karte-notiz", f.eigene_klausur || "Datum unbekannt"));
    kasten.append(zz, el("div", "hinweis",
      "Eigene Klausur — läuft nicht in der Blockklausur mit."));
    ziel.append(kasten);
  }
}

function landebahnZeichnen(b) {
  const ziel = document.getElementById("landebahn");
  leeren(ziel);
  const bahn = b.landebahn;

  if (!bahn.hat_nenner) {
    const kasten = el("div", "leerkasten");
    kasten.append(el("b", null, "Stofflisten fehlen"),
      el("p", null, "Ohne Themenzahl je Fach gibt es keinen Nenner — und ohne Nenner keinen Balken. " +
                    "Kein „0 Tage“, sondern: noch nicht gemessen."));
    ziel.append(kasten);
    return;
  }

  const laengste = Math.max(bahn.tage_bis_klausur || 0, ...bahn.zeilen.map((z) => z.tage || 0), 1);
  const behaelter = el("div", "bahn");
  behaelter.style.paddingTop = "18px";

  if (bahn.tage_bis_klausur !== null) {
    const marke = el("div", "bahn-marke");
    // Die Linie sitzt über der Spur, nicht über der Fachspalte — sonst
    // vergleicht man Balken mit einer Skala, die woanders anfängt.
    marke.style.left = `calc(200px + (100% - 320px) * ${bahn.tage_bis_klausur / laengste})`;
    marke.style.top = "18px";
    marke.append(el("span", null, "KLAUSUR"));
    behaelter.append(marke);
  }

  for (const z of bahn.zeilen) {
    const zeile = el("div", "bahn-zeile");
    const fach = el("div", "fach");
    fach.append(el("span", "strich"), el("span", null, z.name));
    const spur = el("div", "bahn-spur");
    const balken = el("div", "bahn-balken" + (z.ampel === "rot" ? " rot" : z.ampel === "gelb" ? " gelb" : ""));
    balken.style.width = `${((z.tage || 0) / laengste) * 100}%`;
    spur.append(balken);
    // Ein Fach mit eigenem Termin misst sich nicht an der Blocklinie. Ohne
    // diesen Hinweis läse man den Balken gegen das falsche Datum.
    if (z.eigener_termin) {
      const marke = el("span", "eigen-marke", `eigener Termin ${z.eigener_termin}`);
      marke.style.left = `${((z.tage_bis_klausur || 0) / laengste) * 100}%`;
      spur.append(marke);
      fach.querySelector("span:last-child").title = `Eigene Klausur am ${z.eigener_termin}`;
    }
    zeile.append(fach, spur, el("div", "wert", `${z.tage} Lerntage`));
    behaelter.append(zeile);
  }
  ziel.append(behaelter);

  const summe = el("div", "bahn-summe" + (bahn.reicht === false ? " knapp" : ""));
  const satz = bahn.tage_bis_klausur === null
    ? "Ohne Klausurtermin lässt sich nicht sagen, ob das reicht."
    : bahn.reicht
      ? "Das passt, solange nichts dazukommt."
      : "So reicht es nicht — entweder mehr Tage einplanen oder Themen zusammenlegen.";
  const stark = el("b", null,
    `Zusammen ${bahn.summe_tage} Lerntage benötigt` +
    (bahn.tage_bis_klausur !== null ? `, ${bahn.tage_bis_klausur} Tage bis zur Klausur. ` : ". "));
  summe.append(stark, document.createTextNode(satz));
  summe.append(el("div", "karte-notiz-lang",
    "Gerechnet mit einem Lerntag je Thema, das noch nicht bei Anki angekommen ist."));
  ziel.append(summe);
}

function blockFaecherZeichnen(b) {
  const ziel = document.getElementById("blockFaecher");
  leeren(ziel);
  if (!b.faecher.length) {
    ziel.append(el("div", "karte-text", "Keine Fächer in diesem Block erfasst."));
    return;
  }
  for (const f of b.faecher) ziel.append(fachkarte(f, b.faecher));
}

function fachkarte(f, geschwister) {
  const karte = el("button", "fachkarte" + (f.platzhalter ? " platzhalter" : ""));
  karte.addEventListener("click", () => fachOeffnen(f.id, geschwister));
  const oben = el("div", "oben");
  oben.append(el("span", "strich"), el("span", "name", f.name), el("span", "ampel " + (f.ampel || "")));
  karte.append(oben);

  const stufen = el("div", "stufen");
  for (const name of STUFEN) {
    const wert = (f.stufen || {})[name] || 0;
    const anteil = f.themen_gesamt ? wert / f.themen_gesamt : 0;
    const s = el("span", "stufe" + (anteil >= 1 ? " voll" : anteil > 0 ? " teil" : ""));
    s.title = `${name}: ${wert} von ${f.themen_gesamt || "?"}`;
    stufen.append(s);
  }
  karte.append(stufen);

  const zahlen = el("div", "zahlen");
  zahlen.append(
    el("span", null, f.hat_nenner ? `${f.rueckstand} im Rückstand` : "Stoffliste fehlt"),
    el("span", null, f.takt ? `${f.takt} T/Thema` : ""),
  );
  karte.append(zahlen);

  const a = f.anwesenheit || {};
  karte.append(el("div", "anw", a.erfasst
    ? `${a.anwesend || 0} anwesend · ${a.gefehlt || 0} gefehlt (${a.erfasst} erfasst)`
    : "Anwesenheit nicht erfasst"));
  return karte;
}

function querZeichnen(b) {
  const ziel = document.getElementById("quer");
  leeren(ziel);
  const liste = b.querverbindungen || [];
  if (!liste.length) {
    ziel.append(el("div", "karte-notiz-lang",
      "Noch keine Themen erfasst — Querverbindungen entstehen erst daraus."));
    return;
  }
  for (const q of liste) {
    const zeile = el("div", "quer-zeile");
    zeile.append(el("span", "titel", q.titel));
    const marken = el("div", "marken");
    for (const fach of q.faecher) marken.append(el("span", "quer-marke", fach));
    zeile.append(marken);
    ziel.append(zeile);
  }
}

function ruhendZeichnen(b) {
  const ziel = document.getElementById("ruhend");
  leeren(ziel);
  const liste = b.ruhend || [];
  if (!liste.length) {
    ziel.append(el("div", "karte-notiz-lang", "Alle erfassten Fächer laufen in diesem Block."));
    return;
  }
  for (const f of liste) {
    const zeile = el("div", "ruhe-zeile");
    zeile.append(el("span", "strich"), el("span", "titel", f.name),
                 el("span", "karte-notiz", f.hat_nenner ? `${f.rueckstand} offen` : "nicht erfasst"));
    ziel.append(zeile);
  }
}

/* ---------------------------------------------------------- Seite Orga --- */

const REGELN = [
  "Was ein Datum hat, ist eine Frist. Was ein Zählwerk hat, ist ein Nachweis. Was ein Fenster hat, ist eine Anmeldung.",
  "Ein Nachweis mit Frist 2028 hat 2026 nichts auf „Heute“ zu suchen. Dafür ist der Vorlauf da.",
  "Jede Pflicht braucht eine Fundstelle. Ohne Beleg steht kein Datum da.",
  "Leeres Datum heißt unbekannt, nicht „keine Frist“.",
  "Der nächste konkrete Schritt gehört in die Aufgaben, nicht hierher.",
];

function orgaZeichnen(o) {
  einrichtungZeichnen(o);
  fristenListe("orgaFristen", o.fristen, fristZeile,
    "Keine Fristen erfasst. Die App erfindet keine — bekannt ist hier nichts, nicht null.");
  fristenListe("orgaNachweise", o.nachweise, nachweisZeile,
    "Keine Nachweise erfasst.");
  fristenListe("orgaAnmeldungen", o.anmeldungen, anmeldungZeile,
    "Keine Anmeldungen erfasst.");

  const ziel = document.getElementById("orgaRegeln");
  leeren(ziel);
  REGELN.forEach((text, i) => {
    const k = el("div", "regel-kachel");
    k.append(el("div", "nr", String(i + 1).padStart(2, "0")), el("div", "text", text));
    ziel.append(k);
  });
}

function einrichtungZeichnen(o) {
  const ziel = document.getElementById("einrichtung");
  leeren(ziel);
  if (!o.einrichtung_offen) {
    ziel.hidden = true;
    return;
  }
  ziel.hidden = false;
  const zeile = el("div", "zeile");
  zeile.append(el("span", "karte-titel", "Studienstart"),
               el("span", "karte-notiz-lang", "einmalig · verschwindet, sobald alles abgehakt ist"),
               el("div", "dehnen"),
               el("span", "karte-notiz",
                  `${o.einrichtung.length - o.einrichtung_offen} von ${o.einrichtung.length}`));
  ziel.append(zeile);

  const netz = el("div", "schrittnetz");
  for (const s of o.einrichtung) {
    const k = el("div", "schritt" + (s.fertig ? " fertig" : ""));
    const text = el("div");
    text.append(el("span", "titel", s.titel), el("span", "hilfe", s.hilfe));
    k.append(el("span", "punkt"), text);
    netz.append(k);
  }
  ziel.append(netz);
}

function fristenListe(id, liste, bauer, leerText) {
  const ziel = document.getElementById(id);
  leeren(ziel);
  if (!liste || !liste.length) {
    ziel.append(el("div", "karte-text", leerText));
    return;
  }
  const behaelter = el("div", "liste");
  for (const f of liste) behaelter.append(bauer(f));
  ziel.append(behaelter);
}

function fristZeile(f) {
  const zeile = el("div", "orga-zeile");
  const oben = el("div", "oben");
  const rest = el("span", "rest" + (f.tage !== null && f.tage <= 30 ? " bald" : ""),
                  f.tage === null ? "Datum unbekannt" : `in ${tagenWort(f.tage)}`);
  oben.append(el("span", "titel", f.titel), rest);
  zeile.append(oben);
  zeile.append(el("div", "unten", f.frist || `${f.art} · ${f.frist_art}`));
  if (f.regel) zeile.append(el("div", "regel", f.regel));
  return zeile;
}

function nachweisZeile(f) {
  const zeile = el("div", "orga-zeile");
  const oben = el("div", "oben");
  // Fehlt der Ist-Wert, steht „? von 90" da. Eine 0 hieße „nachgesehen,
  // war null" — bei der Prüfungszulassung ist das nicht dasselbe.
  const ist = f.ist === null || f.ist === undefined ? "?" : f.ist;
  oben.append(el("span", "titel", f.titel),
              el("span", "rest", `${ist} von ${f.soll ?? "?"} ${f.einheit || ""}`.trim()));
  zeile.append(oben);

  if (f.soll && f.ist !== null && f.ist !== undefined) {
    const spur = el("div", "zaehlspur");
    const balken = el("div");
    balken.style.width = `${Math.min(100, (f.ist / f.soll) * 100)}%`;
    spur.append(balken);
    zeile.append(spur);
  } else {
    zeile.append(el("div", "unten", "noch nicht erfasst — unbekannt, nicht null"));
  }
  if (f.regel) zeile.append(el("div", "regel", f.regel));
  return zeile;
}

function anmeldungZeile(f) {
  const zeile = el("div", "orga-zeile");
  const oben = el("div", "oben");
  const beschriftung = { offen: "noch nicht offen", laeuft: "läuft", vorbei: "vorbei", unbekannt: "Fenster unbekannt" };
  oben.append(el("span", "titel", f.titel),
              el("span", "chip " + f.fenster_stand, beschriftung[f.fenster_stand]));
  zeile.append(oben);
  zeile.append(el("div", "unten", f.fenster_von || f.fenster_bis
    ? `${f.fenster_von || "?"} bis ${f.fenster_bis || "?"}`
    : "Zeitraum noch zu ermitteln"));
  if (f.regel) zeile.append(el("div", "regel", f.regel));
  return zeile;
}

/* ------------------------------------------------------- Seite Eingang --- */

function plaketteSetzen(n) {
  const p = document.getElementById("eingangZahl");
  p.hidden = !n;
  p.textContent = n || "";
}

function eingangZeichnen(e) {
  const ziel = document.getElementById("eingangInhalt");
  leeren(ziel);
  plaketteSetzen(e.offen);

  if (!e.offen) {
    const leer = el("div", "eingang-leer");
    leer.append(el("b", null, "Nichts im Eingang"),
      el("p", null, "Es wartet nichts auf deine Entscheidung. Vorschläge entstehen aus dem " +
                    "Stundenplan, aus Google und aus Notion — solange dort nichts Neues auftaucht, bleibt es hier leer."));
    ziel.append(leer);
    return;
  }

  if (e.konflikte.length) {
    ziel.append(gruppe("Konflikte", "beide Fassungen bleiben stehen, bis du entscheidest",
      e.konflikte.length, e.konflikte.map(konfliktZeile)));
  }
  const NAMEN = {
    thema: "Themen", termin: "Termine", aufgabe: "Aufgaben",
    frist: "Fristen", karte: "Anki-Karten", material: "Material",
  };
  for (const g of e.gruppen) {
    ziel.append(gruppe(NAMEN[g.art] || g.art, "warten auf dein Ja", g.n,
                       g.eintraege.map(vorschlagZeile)));
  }
}

function gruppe(titel, unter, n, zeilen) {
  const karte = el("section", "karte eingang-gruppe");
  const kopf = el("div", "karte-kopf");
  kopf.append(el("span", "karte-titel", titel), el("span", "karte-notiz-lang", unter),
              el("div", "dehnen"), el("span", "karte-notiz", n));
  karte.append(kopf);
  const liste = el("div", "liste");
  for (const z of zeilen) liste.append(z);
  karte.append(liste);
  return karte;
}

function vorschlagZeile(v) {
  const zeile = el("div", "eingang-zeile");
  zeile.append(el("span", "artmarke", v.art || "?"));

  const mitte = el("div", "mitte");
  mitte.append(el("div", "titel", v.titel));
  if (v.detail) mitte.append(el("div", "detail", v.detail));
  if (v.ziel && v.ziel.zeile) {
    // Die Zeile, die tatsächlich angehängt wird — wörtlich. Wer zustimmt,
    // soll vorher gesehen haben, was in seiner Datei landet.
    mitte.append(el("div", "zielzeile", `${v.ziel.datei}\n${v.ziel.zeile}`));
  }
  zeile.append(mitte);

  const knoepfe = el("div", "knopfreihe");
  for (const [was, text, klasse] of [["uebernehmen", "Übernehmen", "ja"],
                                     ["verwerfen", "Verwerfen", ""],
                                     ["spaeter", "Später", ""]]) {
    const k = el("button", klasse, text);
    k.addEventListener("click", () => entscheiden(v, was, knoepfe, zeile));
    knoepfe.append(k);
  }
  zeile.append(knoepfe);
  return zeile;
}

function konfliktZeile(k) {
  const zeile = el("div", "eingang-zeile");
  zeile.append(el("span", "artmarke konflikt", "Konflikt"));
  const mitte = el("div", "mitte");
  mitte.append(el("div", "titel", k.zeile || k.id || "Konflikt"));
  mitte.append(el("div", "detail",
    `${k.datei || "?"} · ${k.art || "doppelt geändert"} · aufgetreten ${k.titel || "?"}`));
  const gegen = el("div", "gegenueber");
  for (const [wo, was] of [["HIER (Vault)", k.hier], ["DORT (" + (k.quelle || "extern") + ")", k.dort]]) {
    const kasten = el("div");
    kasten.append(el("div", "wo", wo), el("div", "was", was || "—"));
    gegen.append(kasten);
  }
  mitte.append(gegen);
  zeile.append(mitte);
  // Entschieden wird weiterhin in Obsidian — hier wird nur vermerkt, dass es
  // geschehen ist. Sonst stünde der Konflikt für immer im Eingang.
  const knoepfe = el("div", "knopfreihe");
  const fertig = el("button", "ja", "In Obsidian erledigt");
  fertig.title = "Markiert die Zeile in Konflikte.md als entschieden";
  fertig.addEventListener("click", () => konfliktAbschliessen(k, knoepfe));
  knoepfe.append(fertig);
  zeile.append(knoepfe);
  return zeile;
}

async function konfliktAbschliessen(k, knoepfe) {
  for (const b of knoepfe.querySelectorAll("button")) b.disabled = true;
  try {
    const antwort = await fetch("/api/konflikt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: k.id, pruefsumme: k.pruefsumme }),
    });
    const ergebnis = await antwort.json();
    if (!antwort.ok || ergebnis.fehler) throw new Error(ergebnis.fehler || antwort.status);
    zustand.hinweis = { titel: "Konflikt abgeschlossen",
                        text: `${k.id} steht jetzt als entschieden in Konflikte.md.` };
    laden();
  } catch (fehler) {
    zeigeMeldung("Ging nicht", String(fehler.message || fehler), true);
    for (const b of knoepfe.querySelectorAll("button")) b.disabled = false;
  }
}

async function entscheiden(vorschlag, was, knoepfe, zeile) {
  for (const k of knoepfe.querySelectorAll("button")) k.disabled = true;
  try {
    const antwort = await fetch("/api/vorschlag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: vorschlag.id, entscheidung: was }),
    });
    const ergebnis = await antwort.json();
    if (!antwort.ok || ergebnis.fehler) throw new Error(ergebnis.fehler || antwort.status);
    zustand.hinweis = ergebnis.geschrieben
      ? { titel: "Übernommen", text: `Die Zeile steht jetzt in ${ergebnis.geschrieben}.` }
      : { titel: was === "verwerfen" ? "Verworfen" : "Auf später gelegt",
          text: was === "verwerfen"
            ? "Der Vorschlag bleibt als verworfen vermerkt und kommt nicht wieder."
            : "Der Vorschlag bleibt im Eingang stehen." };
    laden();
  } catch (fehler) {
    zeigeMeldung("Ging nicht", String(fehler.message || fehler), true);
    for (const k of knoepfe.querySelectorAll("button")) k.disabled = false;
  }
}

/* --------------------------------------------------- Overlay: ein Fach --- */

const STUFEN_NAMEN = { priming: "Priming", notizen: "Notizen", feynman: "Feynman",
                       loci: "Loci", anki: "Anki" };

/* Laufende Nummer gegen Wettläufe: Zwei schnelle Klicks im Fachwechsler
   stapelten sonst beide Fächer übereinander — zwei Stufenkästen, zwei
   Themenlisten, Titel vom zuletzt fertigen. Die späte Antwort wird verworfen. */
let ovLauf = 0;

async function fachOeffnen(id, geschwister) {
  const lauf = ++ovLauf;
  const overlay = document.getElementById("overlay");
  const koerper = document.getElementById("ovKoerper");
  document.getElementById("ovTitel").textContent = "…";
  document.getElementById("ovUnter").textContent = "wird geladen";
  leeren(koerper);
  if (!overlay.open) overlay.showModal();
  // Der Wechsler gehört zu der Seite, von der aus geöffnet wurde. Sonst zeigt
  // er von „Heute" aus die womöglich veraltete Fächerliste der Blockseite.
  if (geschwister) zustand.ovGeschwister = geschwister;

  let f;
  try {
    // Der gewählte Tag muss mit: sonst zeigt das Overlay Rückstand und Takt
    // von heute, während die Seite dahinter eine andere Woche zeigt.
    const weg = `/api/fach?id=${encodeURIComponent(id)}`
              + (zustand.tag ? `&tag=${zustand.tag}` : "");
    const antwort = await fetch(weg, { cache: "no-store" });
    f = await antwort.json();
    if (!antwort.ok) throw new Error(f.fehler || antwort.status);
  } catch (fehler) {
    if (lauf !== ovLauf) return;
    document.getElementById("ovUnter").textContent = "";
    koerper.append(el("div", "karte-text", String(fehler.message || fehler)));
    return;
  }
  if (lauf !== ovLauf) return;          // inzwischen wurde ein anderes Fach gefragt
  leeren(koerper);

  document.getElementById("ovTitel").textContent = f.name;
  document.getElementById("ovUnter").textContent = [
    f.platzhalter ? "nicht amtlich" : null,
    f.eigene_klausur ? `eigene Klausur ${f.eigene_klausur}` : null,
    f.tage_bis_klausur !== null ? `Klausur in ${tagenWort(f.tage_bis_klausur)}` : "Klausurtermin unbekannt",
  ].filter(Boolean).join(" · ");

  koerper.append(fachKennzahlen(f));
  if (f.punktekonto.zeilen.length) koerper.append(fachPunktekonto(f));
  koerper.append(fachUnten(f));
  koerper.append(fachWechsel(f));
}

function fachKennzahlen(f) {
  const netz = el("div", "ov-drei");

  // Stufen
  const stufen = el("div", "ov-kasten");
  stufen.append(el("div", "marke", "STUFEN"));
  if (f.hat_nenner) {
    const saeulen = el("div", "stufensaeulen");
    for (const name of STUFEN) {
      const wert = f.stufen[name] || 0;
      const s = el("div", "stufensaeule" + (f.optionale_stufen.includes(name) ? " optional" : ""));
      const spur = el("div", "spur");
      const fuell = el("div", "fuell");
      fuell.style.height = `${(wert / f.themen_gesamt) * 100}%`;
      spur.append(fuell);
      s.append(spur, el("div", "name", STUFEN_NAMEN[name]),
               el("div", "wert", `${wert}/${f.themen_gesamt}`));
      saeulen.append(s);
    }
    stufen.append(saeulen);
    stufen.append(el("div", "ov-satz", "Loci ist optional — ein übersprungenes Loci ist kein Rückstand."));
  } else {
    stufen.append(el("div", "ov-satz",
      "Stoffliste fehlt. Ohne Themenliste gibt es keinen Nenner — hier steht deshalb kein Balken bei 0 %."));
  }
  netz.append(stufen);

  // Rückstand
  const rueck = el("div", "ov-kasten" + (f.rueckstand > 0 ? " dunkel" : ""));
  rueck.append(el("div", "marke", "RÜCKSTAND"));
  if (f.hat_nenner) {
    const zeile = el("div", "ov-mitzeile");
    zeile.append(el("b", "ov-gross", f.rueckstand), el("span", null, "Themen ohne Notizen"));
    rueck.append(zeile);
    rueck.append(el("div", "ov-satz", f.aeltestes_offen
      ? `Ältestes offenes Thema: ${f.aeltestes_offen.titel} (${f.aeltestes_offen.tage} Tage her)`
      : "Kein Thema offen."));
  } else {
    rueck.append(el("div", "ov-satz", "unbekannt — nicht null, es ist nur nichts gemessen."));
  }
  netz.append(rueck);

  // Takt
  const takt = el("div", "ov-kasten");
  takt.append(el("div", "marke", "TAKT"));
  if (f.takt) {
    const zeile = el("div", "ov-mitzeile");
    zeile.append(el("b", "ov-gross", f.takt), el("span", null, "Tage je offenem Thema"));
    takt.append(zeile);
    takt.append(el("div", "ov-satz", f.takt > 2
      ? "Genug Luft, solange nichts dazukommt."
      : f.takt >= 1 ? "Eng. Ein Thema am Tag reicht gerade."
                    : "Zu eng — so ist der Stoff bis zur Klausur nicht zu schaffen."));
  } else {
    takt.append(el("div", "ov-satz", f.hat_nenner
      ? "Nicht berechenbar — es fehlt der Klausurtermin oder es ist nichts mehr offen."
      : "unbekannt"));
  }
  netz.append(takt);
  return netz;
}

function fachPunktekonto(f) {
  const k = f.punktekonto;
  const kasten = el("div", "ov-kasten warm");
  kasten.append(el("div", "marke", "ÜBER MEHRERE BLÖCKE · PUNKTEKONTO"));
  for (const z of k.zeilen) {
    const zeile = el("div", "punktezeile");
    zeile.append(el("span", "block", (z.block || "?").toUpperCase()),
                 el("span", null, `${z.art || "Klausur"} · ${z.datum || "Datum offen"}`));
    zeile.append(el("span", "wert" + (z.offen ? " offen" : ""),
      z.offen ? "Ergebnis offen" : `${z.punkte}/${z.max_punkte} · ${z.prozent} %`));
    kasten.append(zeile);
  }
  kasten.append(el("div", "ov-satz", k.prozent === null
    ? "Noch kein Ergebnis verbucht."
    : `Kumuliert ${k.punkte} von ${k.max_punkte} Punkten — ${k.prozent} %. ` +
      (k.reicht ? "Über der 60-%-Grenze." : "Unter der 60-%-Grenze, die je Fach über alle Blöcke gilt.")));
  return kasten;
}

function fachUnten(f) {
  const netz = el("div", "ov-zwei");

  const themen = el("div", "themenliste");
  const kopf = el("div", "karte-kopf");
  kopf.append(el("span", "karte-titel", "Themen"),
              el("span", "karte-notiz-lang", f.hat_nenner
                ? `${f.themen_gesamt} erfasst · ${f.rueckstand} im Rückstand`
                : "keine erfasst"));
  themen.append(kopf);
  if (!f.themen.length) {
    themen.append(el("div", "karte-text", "Keine Themen erfasst."));
  } else {
    for (const t of f.themen) {
      const zeile = el("div", "themenzeile");
      zeile.append(el("span", "titel", t.titel));
      const punkte = el("div", "stufenpunkte");
      for (const name of STUFEN) {
        const p = el("span", "stufenpunkt" + (t.stufen[name] ? " da" : ""), name[0].toUpperCase());
        p.title = `${STUFEN_NAMEN[name]}: ${t.stufen[name] || "offen"}`;
        punkte.append(p);
      }
      zeile.append(punkte);
      zeile.append(el("span", "stand" + (t.rueckstand ? " spaet" : ""),
        t.rueckstand ? "Notizen fehlen" : (t.termin || "ohne Termin")));
      themen.append(zeile);
    }
  }
  netz.append(themen);

  const spalte = el("div", "spalte");

  const material = el("div", "ov-kasten");
  material.append(el("div", "karte-titel", "Material"));
  if (f.material.length) {
    for (const m of f.material) {
      const z = el("div", "materialzeile");
      z.append(el("span", "typ", m.typ), el("span", "name", m.name),
               el("span", "karte-notiz", `${Math.round(m.groesse / 1024)} kB`));
      material.append(z);
    }
  } else {
    material.append(el("div", "ov-satz", f.material_ordner
      ? `Keine Dateien in ${f.material_ordner}.`
      : "Kein Materialordner im Fach hinterlegt."));
  }
  spalte.append(material);

  const ankiK = el("div", "ov-kasten");
  ankiK.append(el("div", "karte-titel", "Anki-Deck"));
  const a = f.anki || {};
  if (a.stand === "ok") {
    const meins = (a.faecher || []).find((z) => z.deck === f.anki_deck);
    ankiK.append(el("div", "ov-satz",
      `${f.anki_deck || "kein Deck hinterlegt"}\n${meins ? `${meins.n} Karten fällig` : "Deck gibt es noch nicht"}`));
  } else {
    ankiK.append(el("div", "ov-satz", `${ankiUeberschrift(a)} — Kartenzahlen unbekannt.`));
  }
  spalte.append(ankiK);

  const anw = el("div", "ov-kasten");
  anw.append(el("div", "karte-titel", "Anwesenheit"));
  const z = f.anwesenheit || {};
  anw.append(el("div", "ov-satz", z.erfasst
    ? `${z.anwesend || 0} anwesend, ${z.gefehlt || 0} gefehlt, ${z.entschuldigt || 0} entschuldigt (${z.erfasst} Termine erfasst)`
    : "Nicht erfasst — nicht „0 gefehlt“."));
  if (f.anwesenheit_regel) anw.append(el("div", "ov-satz", f.anwesenheit_regel));
  spalte.append(anw);

  netz.append(spalte);
  return netz;
}

function fachWechsel(f) {
  const reihe = el("div", "fachwechsel");
  const liste = zustand.ovGeschwister || [];
  for (const andere of liste) {
    const k = el("button", null, andere.name);
    if (andere.id === f.id) k.setAttribute("aria-current", "true");
    else k.addEventListener("click", () => fachOeffnen(andere.id));
    reihe.append(k);
  }
  return reihe;
}

/* ------------------------------------------------ Seite Einstellungen --- */

function einstellungenZeichnen(e) {
  document.getElementById("konfigPfad").textContent = e.konfig;
  const ziel = document.getElementById("einstellungenInhalt");
  leeren(ziel);

  const netz = el("div", "orga-spalten");

  const google = el("section", "karte polster");
  google.append(el("div", "karte-titel", "Google Calendar"));
  google.append(el("div", "ov-satz", e.google.stand === "ok"
    ? `Verbunden, Zugriff ${e.google.modus}.`
    : "Nicht verbunden."));
  for (const k of e.google.kalender) {
    const z = el("div", "materialzeile");
    z.append(el("span", "typ", e.google.bereiche[k.id] || "extern"),
             el("span", "name", k.name));
    google.append(z);
  }
  google.append(el("div", "ov-satz",
    "Schreiben nach Google läuft nicht von hier, sondern über den Sync-Ausgang."));
  netz.append(google);

  const ankiK = el("section", "karte polster");
  ankiK.append(el("div", "karte-titel", "Anki"));
  ankiK.append(el("div", "ov-satz", e.anki.stand === "ok"
    ? `Verbunden über ${e.anki.adresse}, Deckschema ${e.anki.deck_praefix}::<Fach>.`
    : `${ankiUeberschrift(e.anki)}: ${e.anki.text || "keine Verbindung"}. ` +
      "Solange das so ist, ist die Fälligkeit unbekannt — nicht null."));
  netz.append(ankiK);

  const rest = el("section", "karte polster");
  rest.append(el("div", "karte-titel", "Vault und Ablage"));
  for (const [name, wert] of [["Vault", e.vault], ["Konfiguration", e.konfig],
                              ["Port", e.port], ["Notion", e.notion.hinweis],
                              ["Schnappschuss", e.schnappschuss.aktiv ? "aktiv" : "aus"]]) {
    const z = el("div", "materialzeile");
    z.append(el("span", "typ", name), el("span", "name", String(wert)));
    z.title = String(wert);
    rest.append(z);
  }
  netz.append(rest);

  ziel.append(netz);
}

/* --- Hinweise --- */

/* Eine fehlende Datei ist kein leerer Datenbestand. Ohne diesen Hinweis
   stünde nach einer Umbenennung in Obsidian überall „nichts erfasst" — und
   das läse sich wie eine Tatsache statt wie ein Fehler. */
function maengelZeichnen(quelle) {
  const liste = (quelle && quelle.maengel) || [];
  if (!liste.length) return;
  zeigeMeldung(
    liste.length === 1 ? "Eine Datei fehlt" : `${liste.length} Dateien fehlen`,
    liste.map((m) => `${m.datei} — ${m.grund}`).join(" · ") +
      ". Was daraus käme, steht nirgends: nicht „nichts erfasst“, sondern ungelesen.",
    true,
  );
}

function hinweiseZeichnen(d) {
  const g = d.google || {};
  if (g.stand === "fehler") {
    zeigeMeldung("Google nicht erreichbar",
      `${g.text} — der Kalender zeigt deshalb nur, was im Vault steht. Das ist keine leere Woche, sondern eine unvollständige.`, true);
  }
  if (g.stand === "nicht_eingerichtet") {
    zeigeMeldung("Google ist nicht verbunden",
      "Im Wochenraster stehen nur Vault-Termine.", false);
  }
  if (d.block && d.block.platzhalter) {
    zeigeMeldung("Der Themenblock ist eine Vermutung",
      "Beginn, Ende und Klausurtermin stammen aus der Recherche, nicht aus einem Dokument der Fakultät. " +
      "Sie werden beim ersten echten Stundenplan überschrieben.", false);
  }
}

/* ------------------------------------------------------------ Bedienung --- */

function verdrahten() {
  for (const knopf of document.querySelectorAll("button[data-seite]")) {
    knopf.addEventListener("click", () => {
      zustand.seite = knopf.dataset.seite;
      for (const anderer of document.querySelectorAll(".reiter button[data-seite]")) {
        if (anderer === knopf) anderer.setAttribute("aria-current", "page");
        else anderer.removeAttribute("aria-current");
      }
      laden();
    });
  }

  const overlay = document.getElementById("overlay");
  document.getElementById("ovZu").addEventListener("click", () => overlay.close());
  // Klick neben den Inhalt schließt. <dialog> liefert dafür keinen eigenen
  // Haken — der Klick landet auf dem Dialog selbst, nicht auf dem Backdrop.
  overlay.addEventListener("click", (e) => {
    const kasten = overlay.getBoundingClientRect();
    const daneben = e.clientX < kasten.left || e.clientX > kasten.right
                 || e.clientY < kasten.top || e.clientY > kasten.bottom;
    if (daneben) overlay.close();
  });

  document.getElementById("wocheZurueck").addEventListener("click", () => {
    zustand.tag = plusTage(zustand.tag || zustand.daten.heute, zustand.sicht === "tag" ? -1 : -7);
    laden();
  });
  document.getElementById("wocheVor").addEventListener("click", () => {
    zustand.tag = plusTage(zustand.tag || zustand.daten.heute, zustand.sicht === "tag" ? 1 : 7);
    laden();
  });
  document.getElementById("wocheHeute").addEventListener("click", () => { zustand.tag = null; laden(); });
  document.getElementById("neuLaden").addEventListener("click", () => laden());

  for (const knopf of document.querySelectorAll(".schalter button")) {
    knopf.addEventListener("click", () => {
      zustand.sicht = knopf.dataset.sicht;
      for (const anderer of document.querySelectorAll(".schalter button")) {
        anderer.setAttribute("aria-pressed", String(anderer === knopf));
      }
      zeichnen();
    });
  }

  const filter = document.getElementById("nurStudium");
  filter.addEventListener("click", () => {
    zustand.nurStudium = !zustand.nurStudium;
    filter.setAttribute("aria-pressed", String(zustand.nurStudium));
    zeichnen();
  });
}

verdrahten();
laden();
setInterval(laden, 5 * 60 * 1000);
