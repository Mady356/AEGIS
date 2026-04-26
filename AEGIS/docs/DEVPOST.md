# AEGIS — Devpost project page (V4.1)

> Maria Chen is an EMT in rural Colorado, 70 minutes from the nearest trauma
> center. Last winter she responded to a snowmobile crash in a canyon with no
> cellular coverage. She made the call alone. AEGIS exists for the next time
> Maria takes that call.

AEGIS is a fully offline medical documentation interface for trained operators
in austere environments. The local LLM extracts structured facts from voice
transcripts, retrieves protocol references with citations, surfaces compliance
reminders, and produces signed handoff packets — entirely on the operator's
hardware, with no network required and no data ever leaving the device.

**AEGIS is a documentation interface, not a clinical advisor. The local LLM
extracts, retrieves, and summarizes — it does not prescribe.** This is the
positioning that makes AEGIS defensible, demoable, and procurement-credible.
Clinical decisions remain entirely with the operator.

---

## Deployment Model and Buyer Profile

AEGIS is professional medical equipment, not a consumer product.

**The buyer** is the institution that employs trained medical operators:
EMS agencies, military medical units, maritime operators, correctional
healthcare providers, indigenous and rural health systems, disaster response
organizations, humanitarian aid organizations.

**The user** is the trained operator: paramedic, combat medic, ship's
corpsman, correctional nurse, community health worker, field clinician.

**The hardware** sits where the work happens: in the ambulance bay, the
medic's kit, the ship's sick bay, the rural clinic. The operator interacts
through any local display device — tablet, phone, ruggedized handheld — over
a private link with no internet dependency.

**Reference target:** ASUS Ascent GX10 ($3–4K) or equivalent compact AI
workstation. The same architecture runs on M-series Macs, NVIDIA Jetson
boards, and high-end mobile devices. Hardware in this class follows the
trajectory of consumer compute: capability doubles roughly every 18–24
months, price stays flat or declines.

Per-encounter cost across a typical service lifespan: **cents.**

### Institutional buyers

- **Rural EMS agencies** — approximately 12,000 US agencies, of which 60%
  serve rural populations. Capital expenditure cycles every 7–10 years.
- **Military medical units** — Department of Defense procurement, including
  SBIR/STTR programs specifically funding austere-environment medical AI.
- **Maritime operators** — commercial shipping, offshore platforms, cruise
  lines, Coast Guard. Existing investment in onboard medical equipment is
  established.
- **Correctional healthcare contractors** — Wellpath, Corizon, and equivalents
  operate under constitutional adequacy requirements with air-gapped network
  constraints.
- **Indigenous and rural health systems** — Indian Health Service, tribal
  health authorities, federally qualified health centers serving low-resource
  populations.
- **Humanitarian organizations** — Médecins Sans Frontières, ICRC, UN agencies.
  Established procurement budgets for field medical equipment in environments
  with limited or hostile network access.

📄 **Read the AEGIS Pilot Brief** — a one-page deployment proposal for rural
EMS, generated from the live AEGIS system at runtime:
[`aegis_data/pilot_brief.pdf`](../aegis_data/pilot_brief.pdf)

---

## The Gap AEGIS Addresses

> **Hemorrhage causes 80% of preventable combat deaths**, most of which are
> survivable with timely intervention.
> *— Joint Trauma System CPG, Battlefield Trauma Care, 2021*

> **Rural Americans wait an average of 23 minutes for ambulance arrival**,
> nearly twice the urban median.
> *— NHTSA Rural EMS Service Profile, 2023*

> **Maritime medical evacuations cost an average of $200,000 USD** and
> require 4–12 hours before specialist contact is possible.
> *— International Maritime Medical Service Reports, 2022*

> **In federal correctional facilities, inadequate medical care is a
> documented contributing factor in 1 in 3 inmate deaths.**
> *— Bureau of Justice Statistics, Mortality in State and Federal Prisons,
> 2019*

> **90% of healthcare workers in low-resource settings work without
> specialist consultation when needed.**
> *— WHO Global Strategy on Human Resources for Health, 2016*

---

## What AEGIS does (the four LLM jobs)

1. **Extraction** — voice transcript → structured facts. Every extracted fact
   carries a verbatim transcript span as a "receipt" the operator can verify.
2. **Reference QA** — operator question → cited answer or refusal. The LLM
   refuses when the retrieved corpus does not support the question. Every
   citation resolves to a real PDF in the `Reference/` folder, viewable at
   the cited page.
3. **Nudges** — encounter state → protocol-cited reminders for steps that
   are overdue or out of sequence.
4. **After-action review** — completed encounter → cited review included in
   the signed handoff packet.

## Cryptographic guarantees

- SHA-256 integrity chain on all encounter events
- Ed25519 device signatures on handoff packets
- All keys generated locally on first run; no keys leave the device
- Signed handoff packet ships with `verify_handoff.py` so any third party
  can verify on a clean machine

## Built with

Python · FastAPI · Pydantic · ChromaDB · faster-whisper · Ollama · Gemma 2 ·
nomic-embed-text · cryptography (Ed25519) · reportlab · SQLite + SQLCipher ·
HTML / CSS / vanilla JS (no framework) · Major Mono Display · Fraunces ·
JetBrains Mono · Inter

## Try it yourself

```bash
git clone <repo> && cd AEGIS
./bringup.sh           # 5-minute fresh-laptop install
# then open http://127.0.0.1:8000/
```

The bring-up script installs Ollama, pulls Gemma + nomic-embed-text, sets up
the Python venv, generates the device keypair, ingests the corpus, runs the
eval suite, and starts the backend. If anything fails, the script halts with
a specific diagnostic.
