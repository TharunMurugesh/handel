# Handel — Requirements Document

| | |
|---|---|
| **Project** | Handel |
| **Hackathon** | Tech4Bharat 2026 (JanAI Mass Entrepreneurship Challenge, GAVS 2026) |
| **Problem statement** | 4.1 — Small factories overpay for raw material and quote orders at a loss |
| **Theme / tag** | Theme 4: Manufacturing & Industry · **Agentic AI** |
| **Version** | 0.1.3 |
| **Date** | 2026-11-19 |
| **Related** | `00-field-research-plan.md` · `02-specification.md` · `03-architecture.md` (next) |

### Change log

| Version | Changes |
|---|---|
| 0.1 | First draft from official sources |
| 0.1.1 | Competitive bidding (FR-BUY-08), supplier deals (FR-BUY-11), price benchmarks (FR-BUY-12) |
| 0.1.2 | After review: buyer reach raised to Must, with capacity referral (FR-MKT-01, FR-MKT-03); transporter quotes (FR-BUY-13); relationship mode (FR-BUY-14); cost-rate builder (FR-QUO-08); DPDP Act compliance (DT-05); channel independence (NF-10); section order fixed |
| 0.1.3 | No field visits possible: FD-01 to FD-04 declared not met; desk research (FD-07) and honest test data (FD-08) added. See `00-desk-research.md`. |

---

## 1. Purpose and scope

This document lists the requirements Handel must meet. Every requirement comes from an official Tech4Bharat 2026 source, and each one cites that source.

It says **what** Handel must do, not **how**. Technology, channels, models and data design belong in the specification and architecture documents.

Work order:
1. Meet every **Must** requirement.
2. Meet every **Should** requirement.
3. Only then start the add-ons in [section 14](#14-candidate-add-ons-deferred).

Version 0.2 of this document will follow field research (FD-04, `00-field-research-plan.md`). Some requirements may change when field findings contradict the problem statement.

## 2. Sources

| Key | Source | Where |
|---|---|---|
| **PS** | Problem statement 4.1 (all nine sections) | Problem statements brochure, p. 10 |
| **BX-Use** | "How to use these statements" | Brochure, pp. 2–3 |
| **BX-Build** | "What we expect you to build" | Brochure, p. 3 |
| **BX-Cond** | "Conditions every solution works within" | Brochure, p. 3 |
| **BX-Eval** | "Evaluation" | Brochure, p. 3; site FAQ |
| **WEB-Rules** | Rules and eligibility | thegavshackathon.com/rules |
| **WEB-Time** | Timeline | thegavshackathon.com/timeline |
| **WEB-FAQ** | FAQ | thegavshackathon.com/faq |
| **LAW-DPDP** | Digital Personal Data Protection Act, 2023, and its Rules | Government of India |

Brochure: https://thegavshackathon.com/docs/Tech4Bharat-2026-Problem-Statements.pdf

PS section names used in citations: *Problem*, *Who*, *Today*, *Cost*, *Others*, *Hard*, *Boundaries*, *Field Q1–Q6*, *Money*.

## 3. Conventions

**Priority**
- **Must**: a source requires it explicitly, or the problem statement names it as part of the problem. Missing it risks disqualification or a direct loss of score.
- **Should**: the problem statement or judging criteria directly imply it.
- **Could**: an add-on, deferred until all Must and Should requirements are met.

**ID prefixes**

| Prefix | Group |
|---|---|
| HC | Hackathon constraints |
| ST | Stakeholders |
| FR-BUY | Functional: buying raw material |
| FR-QUO | Functional: costing and quoting |
| FR-MKT | Functional: reaching buyers |
| FR-POOL | Functional: buying together |
| AG | Agentic behaviour |
| BD | Boundaries |
| NF | Non-functional (operating conditions) |
| DT | Data, consent and privacy |
| FD | Field research |
| EV | Evaluation |

**AC** means acceptance criteria: the testable condition that shows a requirement is met.

## 4. Problem summary

From PS:
- **Who:** Owners of fabrication, plastics, garment and component units (5–50 workers). They handle purchase and quoting themselves, between running the shop floor.
- **Today:**
  - Rates arrive by phone and WhatsApp and get compared on paper.
  - Quotes to buyers are worked out by rule of thumb.
  - Most business comes from a few familiar local buyers.
- **Cost:**
  - Units overpay for material.
  - They take orders that lose money.
  - They miss bids they should have won.
  - They stay dependent on a handful of customers.
- **Why it's hard:**
  - Quotes are unstructured and multilingual.
  - Prices are volatile.
  - Vague buyer specifications must be mapped to what the shop floor can really produce.

The problem has **three parts**, and Handel must address all three:
1. buying (overpaying for material)
2. quoting (quoting at a loss)
3. reach (dependence on a few local buyers)

## 5. Stakeholders

| ID | Stakeholder | Role relative to Handel | Source |
|---|---|---|---|
| ST-01 | **Unit owner** | Primary user. Raises purchase needs, approves awards, approves quotes and sets limits | PS Who |
| ST-02 | Suppliers and traders | Receive requests for quotes and send quotes. Negotiation counterparty | PS Others |
| ST-03 | Buyers and their purchase teams | Send enquiries and receive the unit's quotes | PS Others |
| ST-04 | Transporters | Quote freight. Their charges make up part of landed cost | PS Others |
| ST-05 | Industrial associations and clusters | Group of units. Partner for buying together and referrals | PS Others |
| ST-06 | Neighbouring units | Possible partners in a joint purchase and for referring work | PS Field Q6 |
| ST-07 | JanAI Café operator | Helps in person wherever documents, authentication or physical presence are needed | BX-Cond |

## 6. Hackathon constraints (HC)

| ID | Requirement | Source | Priority |
|---|---|---|---|
| HC-01 | The team has exactly 4 currently enrolled students from recognised Indian institutions. | WEB-Rules, WEB-FAQ | Must |
| HC-02 | The solution addresses problem statement 4.1. | WEB-Rules, WEB-Time | Must |
| HC-03 | The solution is submitted on HackCulture by the deadline, in the published format. *(Deadline and format still to be announced.)* | WEB-Time | Must |
| HC-04 | A **working prototype** is ready before the Grand Finale (27 Dec 2026, Bangalore Palace). The finale is for presenting, demonstrating and judging, not for building. | WEB-Time, WEB-FAQ | Must |
| HC-05 | Original work only, with fair use of tools and data. | WEB-Rules | Must |
| HC-06 | Sandboxed or simulated integrations are allowed **only if disclosed**. | BX-Build, WEB-Rules | Must |
| HC-07 | The solution qualifies as an **Agentic AI system**: "the bar is a system that acts for its user, well beyond answering questions." | PS tag, BX-Build | Must |
| HC-08 | The team follows IP terms for hackathon work once they're published. Pre-existing work stays with the team. | WEB-Rules | Must |

## 7. Functional requirements

### 7.1 Buying raw material (FR-BUY)

| ID | Requirement | Source | Acceptance criteria | Priority |
|---|---|---|---|---|
| FR-BUY-01 | The owner raises a purchase need once (material, specification, quantity, date needed) instead of calling suppliers one by one. | PS Problem ("calling 5–10 suppliers repeatedly") | One request from the owner reaches every selected supplier. The owner makes no supplier calls. | Must |
| FR-BUY-02 | Handel asks suppliers for quotes through channels they already use, or can join in one step. | PS Today ("phone and WhatsApp") | A supplier can respond without installing anything new or creating an account. If a supplier doesn't join, the owner can relay the request and the reply. | Must |
| FR-BUY-03 | Handel accepts quotes in **unstructured, multilingual** form: free text, voice and images of handwritten or printed quotes. | PS Hard | Each format becomes a structured quote: item, rate, unit, quantity, taxes, freight, payment terms, validity and delivery date. Missing fields are marked as missing, not guessed. | Must |
| FR-BUY-04 | Handel converts every quote to a comparable **landed cost**, including transport, loading, taxes, payment and credit terms, and delivery timing. | PS Others ("transporters, who shape landed cost"), Field Q2 ("which costs get missed") | Each quote shows a landed cost per unit with every component listed. Assumed values are labelled as assumptions. | Must |
| FR-BUY-05 | Handel ranks quotes and recommends one, with reasons the owner can understand. | PS Today ("compared on paper") | The owner gets a ranked shortlist, with a plain-language reason for each position. | Must |
| FR-BUY-06 | Handel follows a purchase from start to award: pending replies, follow-ups and deadline. | PS Problem, BX-Build | Each purchase has a visible status at every point until it is awarded or cancelled. | Must |
| FR-BUY-07 | Handel accounts for **price volatility**: every quote carries its date and validity, and stale quotes are flagged or refreshed. | PS Hard ("prices are volatile") | No expired quote is ranked without a warning. | Must |
| FR-BUY-08 | Handel makes suppliers **compete**: it runs downward bidding rounds and negotiates, always within limits the owner sets (see BD-01). | PS Boundaries, PS Problem ("still missing better deals") | Suppliers can lower their offers in at least one round. Every counter-offer is within limits, truthful and logged. | Should |
| FR-BUY-09 | Handel can bring in suppliers beyond the owner's usual contacts to find better deals. | PS Problem ("still missing better deals") | Suppliers outside the owner's list can be added, and their source is shown. | Should |
| FR-BUY-10 | Handel records the time and effort spent on each purchase. | PS Field Q1 | Time per purchase and number of suppliers contacted can be reported. | Should |
| FR-BUY-11 | Suppliers can offer **deals** (surplus lots, lump-sum offers), and Handel matches them to owners who need that material. | PS Problem ("still missing better deals") | A supplier's deal reaches only owners with a matching need, and an owner can respond within their own ceiling. | Should |
| FR-BUY-12 | Handel **benchmarks** each quote against reference prices so the owner can tell whether a rate is fair. | PS Problem, PS Today | Each recommendation shows how it compares with a dated reference price and names the reference's source. | Should |
| FR-BUY-13 | Handel asks **transporters for freight quotes** when material isn't delivered, and uses the best one in landed cost. | PS Others ("transporters, who shape landed cost") | For ex-yard quotes, at least one real freight quote is requested. The landed cost shows whether freight is quoted or estimated. | Should |
| FR-BUY-14 | The owner can protect **relationship suppliers** (e.g. those who give credit) from bidding rounds, while still comparing their quotes. | PS Others (suppliers), PS Boundaries | Each supplier can be set to "compete" or "relationship". Relationship suppliers get no rank-feedback rounds. | Should |

### 7.2 Costing and quoting (FR-QUO)

| ID | Requirement | Source | Acceptance criteria | Priority |
|---|---|---|---|---|
| FR-QUO-01 | Handel accepts buyer enquiries, including **vague specifications** (text, voice, photos of drawings or samples). | PS Hard | Each enquiry becomes a structured job description. Unclear points are listed. | Must |
| FR-QUO-02 | Handel maps the enquiry to **what the shop floor can actually produce**. | PS Hard | Handel holds a capability profile for the unit (machines, processes, materials, capacity). Work the unit can't do, or that is ambiguous, is flagged, and clarifying questions are drafted. | Must |
| FR-QUO-03 | Handel builds a cost estimate from current material rates, process or machine cost, scrap, overhead, freight and margin. | PS Problem ("costing is approximate") | An itemised cost sheet in which every line traces to its input and the input's date. | Must |
| FR-QUO-04 | Handel warns before any quote that is **below cost**. | PS Cost ("take orders that lose money") | A quote below the computed cost is always flagged before it can be sent. | Must |
| FR-QUO-05 | The owner approves every quote before it goes to a buyer (see BD-03). | PS Boundaries, BX-Build | No quote is sent without a recorded owner approval. | Must |
| FR-QUO-06 | Handel shows a competitive price range (floor and target) so the unit doesn't lose bids it could win. | PS Cost ("miss bids they should have won") | Every cost sheet shows a floor price and a target price. | Should |
| FR-QUO-07 | Handel compares how a job actually turned out against its quote, to improve future costing. | PS Field Q4 | After a job, actual cost can be recorded against quoted cost and the difference reported. | Should |
| FR-QUO-08 | Handel **derives the unit's cost rates** (machine-hour rate, overhead, labour) from information the owner actually has: power bill, wages, rent, machine list and past jobs. It does not assume the owner knows these rates. | PS Today ("quotes are worked out by rule of thumb"), PS Problem ("costing is approximate") | An owner who doesn't know their machine-hour rate can still get a cost sheet. Each derived rate shows how it was calculated. | Must |

### 7.3 Reaching buyers (FR-MKT)

| ID | Requirement | Source | Acceptance criteria | Priority |
|---|---|---|---|---|
| FR-MKT-01 | Handel helps the unit **win work beyond its usual few buyers**. | PS Problem ("rarely sell beyond their local network"), PS Cost ("dependent on a handful of customers", "miss bids they should have won") | The unit can receive enquiries from at least one source outside its existing buyers (see FR-MKT-03), and can answer any enquiry with a costed quote quickly enough to bid. | Must |
| FR-MKT-02 | Handel records where each enquiry came from. | PS Field Q5 | The source of each enquiry can be reported. | Should |
| FR-MKT-03 | **Capacity referral:** when a unit can't make a job, or is full, Handel can offer the enquiry to nearby Handel units that can, with consent from both sides. Units can receive work this way. | PS Problem, PS Others (associations and clusters), Field Q5 | A declined enquiry can be referred to a matching unit. The receiving unit sees only what the referring owner and buyer allow. | Must |

### 7.4 Buying together (FR-POOL)

| ID | Requirement | Source | Acceptance criteria | Priority |
|---|---|---|---|---|
| FR-POOL-01 | Neighbouring units can combine purchases of the same material. | PS Field Q6, PS Others (clusters) | Two or more units' needs can be merged into one request for quotes. | Should |
| FR-POOL-02 | Every participant can see how cost and quantity are split, and each unit commits and pays only its own share. | PS Boundaries (a person makes every payment) | Each unit sees the full split and approves its own share separately. | Should |

## 8. Agentic requirements (AG)

These come directly from the brochure's definition of an Agentic AI system (BX-Build). All are **Must**.

| ID | Requirement | Acceptance criteria |
|---|---|---|
| AG-01 | **Pursues a goal over many steps** on behalf of the user. | One purchase need runs from request to quotes, comparison, shortlist and award request without the owner driving each step. |
| AG-02 | **Plans.** | Each case has an explicit plan that is updated as things change. |
| AG-03 | **Acts in external systems.** Sandboxing is allowed if disclosed (HC-06). | Handel sends and receives messages with suppliers, transporters and buyers itself. |
| AG-04 | **Keeps memory of the case**, and across cases. | Case history, supplier responses, prices and past quotes are kept and reused. |
| AG-05 | **Recovers when something fails.** | Each scenario is shown working: a supplier doesn't reply, a quote can't be read, the connection drops mid-case, a price changes after it was quoted. |
| AG-06 | **Seeks human approval** before any action involving money, legal commitment or personal data. | Awards, payments, outgoing quotes, referrals and sharing of personal data all wait for recorded approval. |
| AG-07 | Goes **well beyond answering questions**. | The demo shows actions Handel took for the owner, not only answers it gave. |

## 9. Boundaries (BD)

| ID | Requirement | Source | Priority |
|---|---|---|---|
| BD-01 | Any negotiation stays within limits the owner sets. | PS Boundaries | Must |
| BD-02 | **A person makes every award and payment.** Handel never awards an order or pays anyone on its own. | PS Boundaries | Must |
| BD-03 | A quote to a buyer is a commitment and goes out only after the owner approves it. | BX-Build (legal commitment) | Must |
| BD-04 | Personal data of owners, suppliers or buyers is shared only with approval. | BX-Build | Must |

## 10. Non-functional requirements: operating conditions (NF)

From BX-Cond unless noted otherwise.

| ID | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| NF-01 | **Voice-first.** | Every core owner action can be done by voice. | Must |
| NF-02 | **Vernacular**: works in the users' own languages. | At least the languages confirmed in field research (OQ-04). | Must |
| NF-03 | Handles **mixed-language** input. | Mixed-language speech and text are understood. | Must |
| NF-04 | Usable with **limited literacy**. | Core tasks can be done without reading long text. | Must |
| NF-05 | Runs on **entry-level Android** phones. | Tested on a low-end Android device. | Must |
| NF-06 | Copes with **patchy connectivity**. | No loss of data or case progress when the connection drops. Work resumes when it returns. | Must |
| NF-07 | Offers an **assisted path through a JanAI Café** wherever documents, authentication or physical presence are needed. | An operator can complete onboarding and assisted steps for a unit. | Must |
| NF-08 | Fits the owner's day: usable in short interactions between shop-floor work (PS Who). | Each owner interaction takes only a few minutes. | Should |
| NF-09 | **Explainable**: every recommendation and number can be traced to its inputs (PS Hard, BX-Eval "quality of AI"). | The owner can ask "why?" about any figure and get its inputs. | Should |
| NF-10 | **Independent of any one messaging channel**: Handel can work over more than one chat app without changing its logic (PS Today, NF-05). | The same case can run over at least two channels. | Should |

## 11. Data, consent and privacy (DT)

| ID | Requirement | Source | Priority |
|---|---|---|---|
| DT-01 | **Explicit consent** from the owner and from every supplier, transporter or buyer whose data Handel processes. | BX-Cond, LAW-DPDP | Must |
| DT-02 | Collect only the data the task needs. | BX-Cond, LAW-DPDP | Must |
| DT-03 | **Mock integrations are clearly labelled**, in the product and in the demo. | BX-Cond, HC-06 | Must |
| DT-04 | Keep an audit trail of every action Handel takes and every approval the owner gives. | Derived from AG-06, BD-01 to BD-04 | Should |
| DT-05 | Comply with the **DPDP Act, 2023**:<br>- a plain-language notice in the person's language<br>- consent that can be withdrawn<br>- access, correction and erasure on request<br>- a named grievance contact<br>- use only for the stated purpose | LAW-DPDP | Must |

## 12. Field research (FD)

> **Status (2026-11-19): field visits are not possible before the build.** FD-01 to FD-04 are **not met** for this submission. This is a known, declared gap.
> - **Mitigation:** desk research (FD-07, `00-desk-research.md`) and honestly labelled team-made test data (FD-08).
> - **Validation after submission:** `00-field-research-plan.md`, if time allows.
> - **In the pitch:** say this plainly. Never present desk or team-made data as field findings.

| ID | Requirement | Source | Priority |
|---|---|---|---|
| FD-01 | Take the statement into the field and sit with the unit owners who live with it. | BX-Use | Must |
| FD-02 | Answer the six field questions with evidence:<br>1. How many suppliers does the owner call for a typical purchase, and how long does it take?<br>2. How are quotes compared, and which costs get missed?<br>3. How was the last quote to a buyer worked out?<br>4. How often has an order turned out to be a loss?<br>5. Where do new buyer enquiries come from today?<br>6. Would neighbouring units buy together? | PS Field Q1–Q6 | Must |
| FD-03 | Test the statement against what we find, and record what was confirmed and what differed. | BX-Use | Must |
| FD-04 | Define the solution only after field research: revise this document to v0.2. | BX-Use | Must |
| FD-05 | **Follow the money**: identify who gains when a unit stops overpaying, and quantify by how much. | PS Money | Must |
| FD-06 | Collect real samples (quotes, enquiries, cost workings) with consent, to test FR-BUY-03 and FR-QUO-03 against. | Supports EV-T2 | Should |
| FD-07 | **Desk research:** support the problem, market, costs and channel choices with cited published sources, each graded for reliability. | Substitute for FD-01 to FD-03 | Must |
| FD-08 | **Honest test data:** measure AI quality on team-made and public datasets with ground truth written in advance. Label them as such everywhere and never present them as field data. | EV-T2, HC-05, DT-03 | Must |

## 13. Evaluation requirements (EV)

Judges score two dimensions (BX-Eval). Weightages are still to be announced. All are **Must**.

| ID | Criterion | What we must be able to show |
|---|---|---|
| **Technical dimension** | | |
| EV-T1 | Architecture | A documented, justified architecture (`03-architecture.md`). |
| EV-T2 | Quality of AI | **Measured** quality on real field data, such as accuracy at reading quotes and cost-estimate error. |
| EV-T3 | Working prototype | All Must requirements shown live (HC-04). |
| EV-T4 | Innovation | What Handel does that existing tools and practice do not (spec §3.1). |
| **Entrepreneurial dimension** | | |
| EV-E1 | Problem relevance | Field evidence (FD-01 to FD-03). |
| EV-E2 | Market | Size and profile of the target units. |
| EV-E3 | Business model | Who pays and why (FD-05). |
| EV-E4 | Scalability | How Handel spreads from one unit to clusters and beyond. |
| EV-E5 | Job creation | Jobs Handel creates or supports, such as café operators and work kept local through referrals. |

## 14. Candidate add-ons (deferred)

These are not requirements yet. We consider them only after every Must and Should is met.

- Material price forecast with a stated confidence
- Supplier reliability scoring (on-time delivery, quote accuracy)
- Freight optimisation for joint purchases, measured against a simple baseline
- Purchase and order records shared with lenders, with consent, to support credit
- Automatic discovery of buyer enquiries from tenders and online marketplaces
- Analytics across a cluster, for industrial associations
- An open marketplace across clusters, grown from Handel's network of suppliers and buyers once it has enough of both

## 15. Open questions

| ID | Question | Resolved by |
|---|---|---|
| OQ-01 | Submission format, deadline and shortlist date | HackCulture / thegavshackathon.com |
| OQ-02 | Judging weightages | Published with registration details |
| OQ-03 | IP terms for hackathon work; cross-college eligibility | Organisers |
| OQ-04 | Which languages the owners and suppliers in our target area use | Field research |
| OQ-05 | Which segment to start with (fabrication, plastics, garment or components) and which materials | Field research |
| OQ-06 | How suppliers actually send quotes, and in what formats | Field research |
| OQ-07 | Usual payment and credit terms, and how they affect the real price | Field research |
| OQ-08 | Whether owners trust an agent to negotiate for them, and within what limits | Field research |
| OQ-09 | Which chat apps owners and suppliers will actually use with an assistant (Telegram, WhatsApp) | Field research |

## 16. Summary

| Group | Must | Should |
|---|---|---|
| HC | 8 | 0 |
| FR-BUY | 7 | 7 |
| FR-QUO | 6 | 2 |
| FR-MKT | 2 | 1 |
| FR-POOL | 0 | 2 |
| AG | 7 | 0 |
| BD | 4 | 0 |
| NF | 7 | 3 |
| DT | 4 | 1 |
| FD | 7 | 1 |
| EV | 9 | 0 |
| **Total** | **61** | **17** |

FD-01 to FD-04 are declared **not met** for this submission (see §12). The Musts that can be met total **57**.
