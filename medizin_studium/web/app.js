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

const RASTER_HOEHE = 812;
// Grundraster. Es wächst nach den Daten, schrumpft aber nicht darunter —
// sonst springt die Höhe der Karte bei jedem Wochenwechsel.
const STUNDE_VON_VORGABE = 8;
const STUNDE_BIS_VORGABE = 18;

const zustand = {
  tag: null,          // null = heute
  sicht: "woche",
  nurStudium: false,
  daten: null,
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

/* --------------------------------------------------------------- Laden --- */

async function laden() {
  if (zustand.laedt) return;
  zustand.laedt = true;
  const ziel = "/api/zustand" + (zustand.tag ? `?tag=${zustand.tag}` : "");
  try {
    const antwort = await fetch(ziel, { cache: "no-store" });
    if (!antwort.ok) throw new Error(`Server antwortet mit ${antwort.status}`);
    zustand.daten = await antwort.json();
    zeichnen();
  } catch (fehler) {
    zeigeMeldung("Der Server antwortet nicht", String(fehler.message || fehler), true);
  } finally {
    zustand.laedt = false;
  }
}

function zeigeMeldung(titel, text, istFehler) {
  const kasten = el("div", "meldung" + (istFehler ? " fehler" : ""));
  kasten.append(el("b", null, titel), el("p", null, text));
  document.getElementById("meldungen").append(kasten);
}

/* ------------------------------------------------------------ Zeichnen --- */

function zeichnen() {
  const d = zustand.daten;
  leeren(document.getElementById("meldungen"));
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
  const proMinute = RASTER_HOEHE / spanne;
  const spalten = `repeat(${anzahl}, minmax(0, 1fr))`;
  // Die Stundenlinien im Hintergrund müssen exakt auf den Beschriftungen
  // sitzen. Ein fester Wert im Stylesheet driftet, sobald sich die Spanne
  // ändert — und sie ändert sich, sobald ein Termin aus dem Raster fällt.
  ziel.style.setProperty("--stunde-hoehe", `${60 * proMinute}px`);

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
    kaestchen.addEventListener("click", () => abhaken(a, kaestchen, zeile));

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

async function abhaken(aufgabe, kaestchen, zeile) {
  kaestchen.disabled = true;
  try {
    const antwort = await fetch("/api/aufgabe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: aufgabe.id, erledigt: true, pruefsumme: aufgabe.pruefsumme }),
    });
    const ergebnis = await antwort.json();
    if (antwort.status === 409) {
      zeigeMeldung("Die Zeile hat sich geändert",
        "Obsidian oder Jarvis haben dieselbe Aufgabe angefasst. Nichts wurde überschrieben — bitte neu laden.", true);
      return;
    }
    if (!antwort.ok || ergebnis.fehler) throw new Error(ergebnis.fehler || antwort.status);
    kaestchen.setAttribute("aria-checked", "true");
    zeile.classList.add("erledigt");
  } catch (fehler) {
    zeigeMeldung("Konnte nicht abhaken", String(fehler.message || fehler), true);
  } finally {
    kaestchen.disabled = false;
  }
}

/* --- Anki --- */

function ankiZeichnen(d) {
  const ziel = document.getElementById("anki");
  leeren(ziel);
  const a = d.anki || { stand: "aus" };

  if (a.stand !== "ok" && a.stand !== "leer") {
    const kasten = el("div", "warnkasten");
    kasten.append(el("b", null, "Anki läuft nicht"),
                  el("span", null, (a.text || "Keine Verbindung zu AnkiConnect.") +
                     " Fälligkeit ist unbekannt — ausdrücklich nicht „0 fällig“."));
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
    kachel.disabled = true;
    kachel.title = f.platzhalter ? `${f.name} — nicht amtlich` : f.name;

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

/* --- Hinweise --- */

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
