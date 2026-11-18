# Alerte seismice INFP + EMSC pentru Home Assistant

> **Sursa alertelor:** alertele provin de la **INCDFP** (Institutul Național de Cercetare-Dezvoltare pentru Fizica Pământului) prin intermediul canalului de Telegram **„Alertă Cutremur”**. Ca rezervă, integrarea folosește datele publice EMSC (seismicportal.eu).

Integrare Home Assistant pentru cutremure, cu două surse:

| Sursă | Cât de repede | Cere cont? |
|---|---|---|
| **INFP prin Telegram** (canalele private de alertă seismică ale INCDFP, la care te abonezi prin `@INFP_alerteCutremur_bot`) | ~30 s după cutremurele mari (măsurat pe cutremurul din Vrancea, M5,3, 18 nov. 2026: +29 s) | Da, un cont Telegram al tău |
| **EMSC** (seismicportal.eu, public) | de la câteva zeci de secunde la câteva minute | Nu |

Pentru fiecare cutremur care trece de pragurile tale (magnitudine și distanță față de locația casei din HA) integrarea:

- declanșează o entitate **`event`** („Cutremur”) cu magnitudine, distanță, adâncime, regiune, ora și sursa;
- actualizează senzori (ultima magnitudine, distanță, ora) și o stare „Telegram conectat”;
- **deduplică** între surse (același cutremur de la INFP și de la EMSC se anunță o singură dată), anunță din nou doar o *revizuire în sus* a magnitudinii și **nu realertează după o repornire** a Home Assistant.

Un **blueprint** transformă evenimentul în alerte pe trepte, cu acțiunile alese de tine (notificări, sirenă, lumini, voce pe boxe).

> **Important.** Alerta vine după ce cutremurul a început. La Vrancea, șocul puternic ajunge în sudul țării după ~40 de secunde, iar INFP anunță în ~30: câștigul e de câteva secunde, nu de minute. Sistemul te trezește și te informează, nu înlocuiește sistemele oficiale și nu garantează livrarea (internet, Telegram, Home Assistant trebuie să funcționeze).

## Avertismente

- **Nu e un produs oficial al INCDFP/INFP.** Datele aparțin Institutului Național de Cercetare-Dezvoltare pentru Fizica Pământului, iar utilizarea locală, fără republicare și fără partajarea link-urilor de invitație, a fost confirmată de INCDFP în scris dezvoltatorului. Nu există un API public oficial pentru integrări terțe; integrarea citește canalele la care te-ai abonat tu.
- **Fiecare utilizator se abonează singur** la canalele INFP, prin botul oficial, și își asumă Termenii și Condițiile acestuia. **Nu partaja link-urile de invitație** primite de la INCDFP (Termenii le interzic).
- Integrarea citește pasiv mesajele din contul tău, **nu le republică** și nu stochează textul lor; păstrează doar parametrii ultimului cutremur (magnitudine, coordonate, adâncime, ora).
- Serviciul INFP e furnizat „ca atare", fără garanții. Alerta poate întârzia sau lipsi (internet, Telegram, Home Assistant). **Nu te baza exclusiv pe ea.**

## Instalare

1. Adaugă depozitul `https://github.com/blitzu/infp-alerte` în HACS (sau în Marketplace-ul Home Assistant) ca *depozit personalizat* de tip *Integration*, instalează „Alerte seismice INFP + EMSC” și repornește Home Assistant.
2. **Setări → Dispozitive și servicii → Adaugă integrare → „Alerte seismice INFP + EMSC”.**
3. Alege **Telegram (INFP) + EMSC** (rapid) sau **Doar EMSC** (fără cont).

### Pregătirea contului Telegram (pentru varianta rapidă)

1. **Recomandat: un cont Telegram separat** (alt număr), folosit doar pentru asta. Sesiunea salvată în Home Assistant poate citi tot contul respectiv, deci nu o da contului tău principal.
2. Cu acel cont, deschide `@INFP_alerteCutremur_bot`, apasă **Start**, acceptă **Termenii și Condițiile** INFP (INCDFP) și abonează-l la canalele private de alertă (abonează-l la toate; integrarea filtrează după mesaj). Citește Termenii: ei stabilesc ce ai voie să faci cu mesajele.
3. Pe <https://my.telegram.org> → *API development tools*, creează o aplicație și notează **api_id** și **api_hash** (gratuit, personal, nu le da nimănui).
4. În integrare introdu api_id, api_hash și numărul de telefon, apoi codul primit în Telegram (și parola de doi pași, dacă există).

Ce citește integrarea: doar mesajele din **canale de difuzare** care arată ca un buletin INFP (conțin `Mw=`, `LAT=`, `LON=`). Restul conținutului contului nu e stocat, logat sau trimis nicăieri. Sesiunea se păstrează în stocarea internă a Home Assistant; dacă expiră, integrarea cere reautentificare.

### Cum verifici că ești abonat

Cu contul conectat în integrare, în aplicația Telegram trebuie să vezi canalele INFP în lista de conversații. Din Home Assistant: *Instrumente pentru dezvoltatori → Acțiuni → „Verifică abonările”* (`infp_alerte.check_subscriptions`) listează, doar după titlu, canalele de difuzare care par INFP din acel cont. Dacă lista e goală, contul nu e abonat (sau canalele au alt titlu). Dovada finală e primul buletin real: apare ca eveniment cu sursa `infp`.

### Opțiuni

*Setări → integrarea → Configurare:* magnitudine minimă (implicit 3,0), distanță maximă (450 km) și dacă folosește și EMSC ca rezervă. Locația de referință e cea a casei din Home Assistant.

## Alerte pe trepte (blueprint)

Importă blueprint-ul cu un clic, apoi creează o automatizare din el (*Setări → Automatizări → Creează automatizare → Folosește un blueprint*):

[![Deschide instanța mea Home Assistant și importă blueprint-ul.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fblitzu%2Finfp-alerte%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Finfp_alerte%2Falerta_pe_trepte.yaml)

(Fișierul e `blueprints/automation/infp_alerte/alerta_pe_trepte.yaml`; HACS instalează doar integrarea, nu și blueprint-urile.) Pentru fiecare treaptă alegi magnitudinea minimă, distanța maximă și acțiunile. Implicit: treapta 1 de la M4,0 sub 350 km, treapta 2 de la M4,5 sub 350 km, treapta 3 de la M5,5 sub 450 km. Se execută doar treapta cea mai înaltă potrivită.

În acțiuni sunt disponibile variabilele `tier`, `magnitude`, `distance_km`, `depth_km`, `region`, `quake_time`, `source`, `revised`.

### Exemple de acțiuni

Notificare critică (trece de „Nu deranja”), iOS și Android în același mesaj:

```yaml
- action: notify.mobile_app_telefonul_meu
  data:
    title: "Cutremur M{{ magnitude }} – {{ region }}"
    message: "La {{ distance_km | round(0) }} km, adâncime {{ depth_km | round(0) }} km, ora {{ quake_time }}."
    data:
      ttl: 0
      priority: high
      channel: alarm_stream
      push:
        interruption-level: critical
        sound: {name: default, critical: 1, volume: 1}
```

Lumini la 100% și sirenă:

```yaml
- action: light.turn_on
  target: {entity_id: all}
  data: {brightness_pct: 100}
- action: siren.turn_on
  target: {entity_id: siren.hol}
```

Voce pe boxe:

```yaml
- action: tts.speak
  target: {entity_id: tts.google_translate_ro_ro}
  data:
    media_player_entity_id: media_player.boxa_living
    message: "Atenție! Cutremur de magnitudine {{ magnitude }} în {{ region }}. Verificați dacă sunt replici."
```

## Cum testezi fără să trezești casa

Serviciul **`infp_alerte.simulate_quake`** (Instrumente pentru dezvoltatori → Acțiuni) declanșează un cutremur de test cu magnitudinea și distanța alese de tine (ocolește pragurile și deduplicarea; sursa apare ca `test`). Blueprint-ul rulează acțiunile treptei potrivite, deci pentru un test liniștit alege o magnitudine mică, de exemplu `magnitude: 4.2`, `distance_km: 120` (treapta 1 cu valorile implicite). Pentru a verifica sirena și luminile folosește o treaptă mai mare, când e momentul potrivit.

## Dezvoltare

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component telethon
.venv/bin/python -m pytest
```

Testele acoperă parserul INFP, deduplicarea, EMSC, pornirea în Home Assistant, persistența după repornire, fluxul de autentificare și blueprint-ul.

## Alternative și mulțumiri

Există și [`ov1d1u/telegram_earthquake_alert`](https://github.com/ov1d1u/telegram_earthquake_alert), care ascultă conversații Telegram alese de utilizator și trimite un eveniment doar cu magnitudinea. Acest proiect e independent și nu folosește cod din el; adaugă coordonate și distanță, deduplicare, EMSC, entități, reautentificare și blueprint.

## Licență

[GPL-3.0](LICENSE). Datele seismice și mesajele aparțin INCDFP, respectiv EMSC; licența se aplică doar codului acestui proiect.

---

# English summary

Home Assistant integration for earthquake alerts using two sources: the Romanian National Institute for Earth Physics (INFP) bot on Telegram (your own account, ~30 s latency for large quakes) and EMSC (public, no account). It exposes an `event` entity plus sensors, deduplicates across sources and across restarts, and ships a blueprint for tiered alerts (notifications, siren, lights, TTS) with actions you choose. Use a **separate Telegram account**: the stored session can read the whole account. Alerts arrive after shaking has started; they do not replace official warning systems.
