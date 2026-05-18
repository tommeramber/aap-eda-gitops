# AAP + EDA GitOps Demo

**Red Hat PS Team — Strategic Customer Demo**  
AAP 2.6.0 on OpenShift 4.18.20

---

## What This Demo Shows

Two GitOps automation scenarios triggered by a Git push to `main`, using **Ansible Automation Platform (AAP)** and **Event-Driven Ansible (EDA)** installed on OpenShift via the Ansible Operator.

| | Scenario A — Direct Apply | Scenario B — Approval Gate |
|---|---|---|
| Trigger | `git push` to `main` | `git push` to `main` |
| EDA fires | `run_job_template` | `run_workflow_template` |
| Approval | None — applies immediately | Email approval via SMTP microservice on OCP |
| Notification | Email / Slack on success | Approval request + status email |

---

## Repository Layout

```
aap-eda-gitops/
├── rulebooks/
│   ├── scenario-a-direct.yml          # EDA rulebook — Scenario A
│   └── scenario-b-approval.yml        # EDA rulebook — Scenario B
├── playbooks/
│   ├── apply-manifest.yml             # Applies changed YAML to OCP + notifies
│   └── send-approval-request.yml      # Sends approval request email (Scenario B)
├── collections/
│   └── requirements.yml               # Ansible collection dependencies
├── microservice/
│   ├── app.py                         # Email approval microservice (Python)
│   ├── requirements.txt               # Python dependencies
│   └── Dockerfile                     # UBI9 container image
├── ocp/
│   ├── sa-and-crb.yaml                # ServiceAccount + ClusterRoleBinding for AAP
│   ├── eda-webhook-route.yaml         # OCP Route to expose EDA webhook
│   ├── email-approver-secret.example.yaml  # Secret template (fill in values)
│   └── email-approver-deploy.yaml     # Deployment for the approval microservice
├── docs/
│   └── DEMO_GUIDE.md                  # Full step-by-step setup and walkthrough
├── .gitignore
└── README.md
```

---

## Quick Start

### Prerequisites

- OpenShift 4.18+ cluster with `cluster-admin`
- AAP 2.6 installed via Operator in the `aap` namespace
- `oc` CLI authenticated to the cluster
- Git repository (this repo) accessible from AAP and EDA

### 1 — OCP Setup

```bash
oc apply -f ocp/sa-and-crb.yaml
oc create token aap-gitops-sa -n openshift-monitoring --duration=8760h
```

### 2 — Configure AAP

1. Create custom credential type **OCP Cluster (SA Token)** — see [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md#2-aap--custom-credential-type--credentials)
2. Create credential `ocp-demo-cluster` using that type
3. Create project `aap-gitops-demo` pointing to this repo
4. Create job template `gitops-apply-networkpolicy` using `playbooks/apply-manifest.yml`
5. For Scenario B: create job template `gitops-send-approval-request` and workflow `gitops-approval-workflow`

### 3 — Configure EDA

1. Create EDA credential pointing to AAP Controller
2. Create EDA project pointing to this repo
3. Create Rulebook Activation for **Scenario A** (`scenario-a-direct.yml`) with Service Name `eda-gitops-webhook`
4. Expose the webhook via OCP Route: `oc apply -f ocp/eda-webhook-route.yaml`

### 4 — Configure GitHub Webhook

- Payload URL: `https://eda-webhook.apps.<cluster-domain>`
- Content type: `application/json`
- Event: **push**

### 5 — Deploy Approval Microservice (Scenario B only)

```bash
# Fill in values first!
cp ocp/email-approver-secret.example.yaml ocp/email-approver-secret.yaml
# edit ocp/email-approver-secret.yaml

oc apply -f ocp/email-approver-secret.yaml -n aap
oc apply -f ocp/email-approver-deploy.yaml -n aap
```

---

## Full Documentation

See **[`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md)** for the complete step-by-step guide including:
- All credential type definitions
- Detailed AAP / EDA UI configuration steps
- Webhook test commands
- Pre-demo checklist
- Live demo walkthrough for both scenarios
- AAP REST API reference for workflow approvals

---

## Lab Environment

All URLs are discovered dynamically from the cluster — no hardcoded values.
Run the bootstrap block in `docs/DEMO_GUIDE.md → Lab Credentials` to export them:

```bash
# AAP Platform Gateway
echo $AAP_URL

# AAP Automation Controller (/api/v2/ endpoint)
echo $AAP_CONTROLLER_URL

# EDA Webhook (after activation and Route are created)
echo $EDA_WEBHOOK_URL
```

> ⚠️ Passwords are not stored in this repo. See `docs/DEMO_GUIDE.md → Lab Credentials` for retrieval commands.

---

## Architecture

**Scenario A — Direct GitOps**
```
SRE → git push → GitHub webhook → EDA Rulebook → AAP Job Template
  → kubernetes.core.k8s applies YAML to OCP → email/Slack notification
```

**Scenario B — Approval Gate**
```
SRE → git push → GitHub webhook → EDA Rulebook → AAP Workflow
  → approval request email → approver replies "approved"
  → SMTP microservice (OCP pod) → AAP API approve
  → workflow resumes → applies YAML to OCP → status notification
```
