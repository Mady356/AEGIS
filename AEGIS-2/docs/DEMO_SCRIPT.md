# AEGIS V4.1 — 90-second demo script

Print three copies. Read this aloud once before the live run. Time it
against a watch. The opening vignette is non-negotiable; everything else
flexes if a moment lands.

---

## 0:00–0:12 — The vignette opening

*Hold up the printed Maria Chen card. Read aloud, slowly:*

> Maria Chen is an EMT in rural Colorado, 70 minutes from the nearest
> trauma center. Last winter she responded to a snowmobile crash in a
> canyon with no cellular coverage. Her patient had a suspected pelvic
> fracture and she had thirty minutes of training on that injury, two
> years earlier. She made the call alone.
>
> AEGIS exists for the next time Maria takes that call.

*Pause for two beats. Then:*

"Everything you're about to see runs entirely on this hardware. No
internet. No data leaves the device. AEGIS does four LLM jobs against
a hand-curated corpus of medical protocols. **It does not prescribe.**"

## 0:12–0:42 — Live voice intake and extraction

1. Press the mic. Speak the GSW intake (or `Ctrl+Shift+1` for the clip).
2. Watch the Live Transcript pane fill with timestamped utterances.
3. Highlighted spans appear as extraction completes.
4. Hover one highlighted span — the extracted fact tooltip surfaces.
5. Type into the Reference QA box:
   *"What's the pediatric paracetamol dose for fifteen kilograms?"*
6. Press ASK. The cited answer appears within 1–2 seconds.
7. Click the citation pill `[WHO-PED-PARACETAMOL]`.
8. Citation overlay opens with the real chunk, score, page, source.
9. **Click `VIEW SOURCE PDF, p. 412`. The actual WHO Pocket Book PDF
   opens in a new tab at page 412.**

## 0:42–1:05 — The tamper demo

1. Click `RECORD` in the top bar.
2. Click `TAMPER (DEMO)` in the integrity footer.
3. Pick an event — any event. Click it.
4. Integrity readout flips: `✗ CHAIN BROKEN AT EVENT #N`.
5. Click `HEAL`.
6. Click `VERIFY INTEGRITY NOW`.
7. Chain restored: `SHA-256 chain · N events · ✓ VERIFIED`.

## 1:05–1:30 — The handoff packet and verification

1. Close the RECORD overlay.
2. Click `GENERATE HANDOFF PACKET` at the bottom right.
3. Watch the AAR type out via typewriter (the only place V4 still uses it).
4. Watch the SHA-256 + Ed25519 + PDF render lines tick in.
5. Click `DOWNLOAD .ZIP`.
6. Hand the judge the USB stick (or guide them to the Downloads folder).
7. In a terminal: `python verify_handoff.py encounter.json`
8. Show: `Signature: VALID ✓` / `Hash: MATCH ✓` / `VALID`.
9. Edit one byte of `encounter.json`. Re-run the verifier.
10. Show: `Signature: INVALID ✗`.

## Close (no extra time)

> "AEGIS is professional medical equipment. The buyer is the institution.
> The user is the trained operator. The hardware sits where the work
> happens. The data never leaves the device. The work is verifiable
> end-to-end."
>
> "The network is optional. Care is not."

---

## Earned demo time (60–180 additional seconds, only if the judge stays)

If the judge wants depth, click `SYS` and walk down the TRUST surface:

- **Product positioning** — read aloud
- **The Gap AEGIS Addresses** — pick one of the five evidence statements
  and read it aloud with its citation
- **Who AEGIS Is For** — Maria Chen vignette in context
- **Deployment Model** — read the closer line: "Per-encounter cost across
  a typical service lifespan: cents."
- **Failure Modes** — pick three the judge might worry about
- **Institutional Buyers** — read the six categories
- **Pilot Brief** — click `Download Pilot Brief (PDF, 1 page)` and hand
  it over

This walk-through is the moment the judge moves from "this is impressive"
to "this team has thought through deployment."

---

## Failure-mode safety nets (don't talk about these unless asked)

| Shortcut             | What it does                                              |
|----------------------|-----------------------------------------------------------|
| `Ctrl+Shift+1/2/3`   | Replay pre-recorded voice clip 1/2/3 if the mic fails     |
| `Cmd+R` on cold open | Skip the intro animation if needed (or press Space/Enter) |
| `Ctrl+Shift+T`       | (V3 hold-over) toggle tamper from outside the RECORD overlay |

If everything else fails, the printed Maria Chen card and the printed
pilot brief PDF are themselves the demo. The vignette + the brief + the
verify script are enough.
