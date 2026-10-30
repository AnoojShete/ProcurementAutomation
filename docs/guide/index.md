# IT Procurement Intelligence Platform

<p class="lede">A company buying laptops, licences or a SaaS subscription goes
through quotes, approvals, a contract, a signature and an invoice. This
platform does the paperwork in between. It reads the documents, sends each
request to the right approvers, drafts the contract and collects the
signature. People still make the decisions.</p>

Student team project, Fractal Analytics 2026–27: Anjali Dinesh Jayashree
More, Vaidehi Jagdeep Sankaye, Niraj Ravindra Sawant and Anooj Vinayak Shete
([System developers](team.md)). Five agents, an assistant, 24 containers on
Docker Compose, 1,409 service tests.

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
