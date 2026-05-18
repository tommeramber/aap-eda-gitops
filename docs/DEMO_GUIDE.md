# AAP + EDA GitOps Demo — Step-by-Step Guide

**Red Hat PS Team | Strategic Customer Technical Briefing**  
AAP 2.6.0 on OpenShift 4.18.20 | May 2026

---

## Lab Credentials

> ⚠️ Passwords are intentionally omitted. Retrieve them using the commands below before starting the demo.

| Component | URL | Username | How to get the password |
|---|---|---|---|
| OpenShift Console | `https://console-openshift-console.apps.cluster-jx4b7.dynamic.redhatworkshops.io` | `admin` | `oc get secret -n kube-system kubeadmin -o jsonpath='{.data.kubeadmin}'` &#124; `base64 -d` — or check your cluster provisioning email |
| AAP Controller | `https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io` | `admin` | See command below |

**Retrieve AAP admin password:**
```bash
oc get secret -n aap \
  $(oc get secret -n aap -o name | grep admin-password | head -1 | cut -d/ -f2) \
  -o jsonpath='{.data.password}' | base64 -d

# Alternative — if installed via AAP Operator with default naming:
oc get secret aap-admin-password -n aap -o jsonpath='{.data.password}' | base64 -d
```

---

## Scenario Comparison

| | Scenario A — Direct Apply | Scenario B — Approval Gate |
|---|---|---|
| Trigger | GitHub push to main | GitHub push to main |
| EDA action | `run_job_template` | `run_workflow_template` |
| AAP component | Job Template | Workflow Template (3 nodes) |
| Approval | None — applies immediately | Email approval via SMTP microservice on OCP |
| Notification | Email/Slack on success | Approval request email + status on completion |
| OCP credential | Custom type with SA token | Same |

---

## Table of Contents

1. [OCP — Service Account Setup](#1-ocp--service-account-setup)
2. [AAP — Custom Credential Type & Credentials](#2-aap--custom-credential-type--credentials)
3. [Git Repository Structure](#3-git-repository-structure)
4. [EDA Rulebooks](#4-eda-rulebooks)
5. [EDA — Project, Activation & OCP Route](#5-eda--project-activation--ocp-route)
6. [Scenario A — Playbook & Job Template](#6-scenario-a--playbook--job-template)
7. [GitHub Webhook Configuration](#7-github-webhook-configuration)
8. [Scenario B — AAP Workflow Template](#8-scenario-b--aap-workflow-template)
9. [Scenario B — Approval Request Playbook](#9-scenario-b--approval-request-playbook)
10. [Email Approval Microservice (Python)](#10-email-approval-microservice-python)
11. [OCP Deployment for the Microservice](#11-ocp-deployment-for-the-microservice)
12. [Demo Walkthrough Checklist](#12-demo-walkthrough-checklist)

---

## 1. OCP — Service Account Setup

Create a `ServiceAccount` with `cluster-admin` in `openshift-monitoring`. AAP will store the resulting token in a custom credential type.

### Step 1 — Create ServiceAccount and ClusterRoleBinding

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: aap-gitops-sa
  namespace: openshift-monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: aap-gitops-sa-cluster-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: aap-gitops-sa
  namespace: openshift-monitoring
```

```bash
oc apply -f ocp/sa-and-crb.yaml
```

### Step 2 — Generate a Long-Lived Token

```bash
# Option A: 1-year token (recommended for labs)
oc create token aap-gitops-sa \
  -n openshift-monitoring \
  --duration=8760h

# Option B: Token Secret (never expires)
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: aap-gitops-sa-token
  namespace: openshift-monitoring
  annotations:
    kubernetes.io/service-account.name: aap-gitops-sa
type: kubernetes.io/service-account-token
EOF

oc get secret aap-gitops-sa-token -n openshift-monitoring \
  -o jsonpath='{.data.token}' | base64 -d
```

### Step 3 — Get the API Server URL

```bash
oc whoami --show-server
# Expected: https://api.cluster-jx4b7.dynamic.redhatworkshops.io:6443
```

---

## 2. AAP — Custom Credential Type & Credentials

### Step 1 — Create Custom Credential Type for OCP

In AAP: **Administration → Credential Types → Add**  
Name: `OCP Cluster (SA Token)`

**Input Configuration (YAML):**
```yaml
fields:
  - id: ocp_api_url
    type: string
    label: OCP API Server URL
  - id: ocp_token
    type: string
    label: OCP ServiceAccount Bearer Token
    secret: true
required:
  - ocp_api_url
  - ocp_token
```

**Injector Configuration (YAML):**
```yaml
env:
  OCP_API_URL: "{{ ocp_api_url }}"
  OCP_TOKEN: "{{ ocp_token }}"
```

### Step 2 — Create OCP Credential

| Field | Value |
|---|---|
| Name | `ocp-demo-cluster` |
| Organization | `Default` |
| Credential Type | `OCP Cluster (SA Token)` |
| OCP API Server URL | `https://api.cluster-jx4b7.dynamic.redhatworkshops.io:6443` |
| OCP SA Bearer Token | *(token from Step 2 above)* |

### Step 3 — Create Git Credential (if repo is private)

| Field | Value |
|---|---|
| Name | `github-gitops-repo` |
| Credential Type | `Source Control` |
| Username | your GitHub username |
| Password/Token | GitHub Personal Access Token (repo scope) |

### Step 4 — Generate AAP Token for the Microservice (Scenario B)

```bash
# <YOUR_AAP_ADMIN_PASSWORD>
# How to obtain: AAP UI → top-right user menu → User Details
# Or retrieve from the AAP operator secret in OCP:
#   oc get secret -n aap -l app=aap -o jsonpath='{.items[0].data.password}' | base64 -d

curl -sk -X POST \
  "https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io/api/v2/users/1/tokens/" \
  -H "Content-Type: application/json" \
  -u admin:<YOUR_AAP_ADMIN_PASSWORD> \
  -d '{"description": "email-approver-microservice", "scope": "write"}'
```

### Step 5 — Create SMTP Credential

Create a custom credential type injecting `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` as env vars — same pattern as the OCP credential type above.

---

## 3. Git Repository Structure

```
aap-eda-gitops/
├── rulebooks/
│   ├── scenario-a-direct.yml
│   └── scenario-b-approval.yml
├── playbooks/
│   ├── apply-manifest.yml
│   └── send-approval-request.yml
├── microservice/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── ocp/
│   ├── sa-and-crb.yaml
│   ├── eda-webhook-route.yaml
│   ├── email-approver-secret.example.yaml
│   └── email-approver-deploy.yaml
├── collections/
│   └── requirements.yml
└── docs/DEMO_GUIDE.md
```

---

## 4. EDA Rulebooks

> Activate **only one rulebook at a time**. Toggle between Scenario A and B in EDA UI.

See `rulebooks/scenario-a-direct.yml` and `rulebooks/scenario-b-approval.yml` in this repo.

---

## 5. EDA — Project, Activation & OCP Route

### EDA Credential (AAP Controller)

| Field | Value |
|---|---|
| Name | `aap-controller-credential` |
| Credential Type | `Red Hat Ansible Automation Platform` |
| URL | `https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io` |
| Username | `admin` |
| Password | `<YOUR_AAP_ADMIN_PASSWORD>` |
| SSL Verify | `False` |

> **How to get the AAP admin password:**
> ```bash
> # From the AAP operator Secret in OCP:
> oc get secret -n aap \
>   $(oc get secret -n aap -o name | grep admin-password | head -1 | cut -d/ -f2) \
>   -o jsonpath='{.data.password}' | base64 -d
> # Or: AAP UI → top-right avatar → User Details → Tokens
> ```

### EDA Project

| Field | Value |
|---|---|
| Name | `aap-gitops-demo` |
| SCM URL | `https://github.com/tommeramber/aap-eda-gitops` |
| Branch | `main` |

### Rulebook Activation (Scenario A)

| Field | Value |
|---|---|
| Name | `gitops-scenario-a-direct` |
| Rulebook | `scenario-a-direct.yml` |
| Service Name | `eda-gitops-webhook` |
| AAP Credential | `aap-controller-credential` |

### Expose EDA Route

```bash
oc apply -f ocp/eda-webhook-route.yaml
oc get route eda-gitops-webhook -n aap -o jsonpath='{.spec.host}'
```

---

## 6. Scenario A — Playbook & Job Template

See `playbooks/apply-manifest.yml`.

### Job Template

| Field | Value |
|---|---|
| Name | `gitops-apply-networkpolicy` |
| Playbook | `playbooks/apply-manifest.yml` |
| Credentials | `ocp-demo-cluster` + SMTP credential |
| Extra Variables: Prompt on Launch | **CHECKED** |

> ⚠️ "Prompt on Launch" is mandatory — EDA passes `repo_url`, `commit_sha`, `changed_files` at runtime.

---

## 7. GitHub Webhook Configuration

| Field | Value |
|---|---|
| Payload URL | `https://eda-webhook.apps.cluster-jx4b7.dynamic.redhatworkshops.io` |
| Content type | `application/json` |
| Events | Push |

```bash
# Test manually:
curl -sk -X POST \
  https://eda-webhook.apps.cluster-jx4b7.dynamic.redhatworkshops.io \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -d '{"ref":"refs/heads/main","after":"abc123","repository":{"clone_url":"https://github.com/tommeramber/aap-eda-gitops"},"commits":[{"modified":["ocp/sa-and-crb.yaml"]}]}'
```

---

## 8. Scenario B — AAP Workflow Template

| Node | Type | Name | Connection |
|---|---|---|---|
| 1 | Job Template | `gitops-send-approval-request` | Start |
| 2 | Approval | `Approve GitOps Change` (24h timeout) | On Success from Node 1 |
| 3 | Job Template | `gitops-apply-networkpolicy` | On Approval from Node 2 |

All nodes: **Extra Variables → Prompt on Launch = CHECKED**

---

## 9. Scenario B — Approval Request Playbook

See `playbooks/send-approval-request.yml`.

Key behaviour: embeds `WFJ-<workflow_job_id>/<approval_node_id>` in the email body so the microservice can target the exact approval node.

---

## 10. Email Approval Microservice (Python)

See `microservice/app.py`, `microservice/Dockerfile`, `microservice/requirements.txt`.

```bash
# Build and push
podman build -t quay.io/YOUR_ORG/email-approver:latest microservice/
podman push quay.io/YOUR_ORG/email-approver:latest
```

---

## 11. OCP Deployment for the Microservice

```bash
# Copy and fill in the secret template
cp ocp/email-approver-secret.example.yaml ocp/email-approver-secret.yaml
# Edit ocp/email-approver-secret.yaml — never commit this file!

oc apply -f ocp/email-approver-secret.yaml -n aap
oc apply -f ocp/email-approver-deploy.yaml -n aap
oc rollout status deployment/email-approver -n aap
oc logs -f deployment/email-approver -n aap
```

---

## 12. Demo Walkthrough Checklist

### Pre-Demo

| # | Task | Verify |
|---|---|---|
| 1 | OCP: `aap-gitops-sa` SA exists | `oc get sa aap-gitops-sa -n openshift-monitoring` |
| 2 | AAP: Custom credential type created | AAP UI → Credential Types |
| 3 | AAP: `ocp-demo-cluster` credential created | AAP UI → Credentials |
| 4 | AAP: project synced | AAP UI → Projects |
| 5 | AAP: job templates created | AAP UI → Templates |
| 6 | AAP: workflow template created (3 nodes) | AAP UI → Templates → Visualizer |
| 7 | EDA: project synced, activation Running | EDA UI → Rulebook Activations |
| 8 | OCP: Route accessible | curl the webhook URL |
| 9 | GitHub: webhook last delivery = 200 | Repo → Settings → Webhooks |
| 10 | Scenario B: `email-approver` pod running | `oc get pods -n aap` |

### Scenario A Steps

1. Show EDA activation Running
2. Edit a NetworkPolicy YAML in Git → commit to main
3. Watch EDA history fire → AAP job starts → manifest applied
4. Show NetworkPolicy in OCP, notification email received

### Scenario B Steps

1. Switch EDA to `scenario-b-approval` activation
2. Push YAML change to main
3. AAP Workflow starts → approval email sent
4. Reply `approved` → microservice calls AAP API
5. Workflow resumes → YAML applied → status email

### AAP Approval API

```bash
# Approve workflow approval ID 42:
curl -sk -X POST \
  "https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io/api/v2/workflow_approvals/42/approve/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

*Generated by Cursor AI — Red Hat PS Team, May 2026*
