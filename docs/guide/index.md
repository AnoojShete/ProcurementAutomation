<div class="hero" markdown>

# IT Procurement Intelligence Platform
**Buying software and hardware for a company, automated end to end** — from a vendor's quote landing in a folder to a signed contract and a matched invoice. AI reads the documents; people step in only where a decision is needed.

[Explore Architecture](overview/architecture.md){ .md-button .md-button--primary }
[Functional Workflow](overview/functional-workflow.md){ .md-button }
[Admin Control Panel](control-panel.md){ .md-button }

</div>

<div class="stat-grid">
  <div class="stat"><b>5</b><span>Cooperating Agents</span></div>
  <div class="stat"><b>1,276</b><span>Automated Tests</span></div>
  <div class="stat"><b>100</b><span>Risk Scorecard Points</span></div>
  <div class="stat"><b>22</b><span>Docker Services</span></div>
</div>

> Student team project, Fractal Analytics 2026–27: Anjali, Vaidehi, Niraj, Anooj.

![System architecture](assets/architecture.png){ .diagram }

## The flow in one line

Document in (upload, email or the `./inbox/input` folder) → read, classified and
validated → purchase request → approval by spend tier → contract generated →
e-signature → signed PDF stored → order → delivery → invoice matched.
Every step is an event on Kafka, and the right person gets an email at each one.

## Where to start

| You want to… | Read |
|---|---|
| Understand the problem and the solution | [Introduction and objectives](overview/introduction.md) |
| See how the parts fit | [System architecture](overview/architecture.md), [Functional workflow](overview/functional-workflow.md) |
| Know what one agent does | [Agents](agents/index.md) |
| Run or administer the platform | [Control Panel](control-panel.md), [Deployment](reference/deployment.md) |
| Call the API | [APIs](reference/apis.md) |
| Check the final review checklist | [Final checklist](reference/checklist.md) |

## Run it

```bash
./run.sh                        # whole stack; ends with "All services healthy."
./scripts/seed-demo-data.sh     # demo vendor, requests, licences, stock
```

Open <http://localhost:8080> and sign in as `admin@demo.example.com`
(password `DemoPass123!`). Then drop a quote PDF into `./inbox/input` and
watch it on **Control Panel**.
