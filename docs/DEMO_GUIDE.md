# AAP + EDA GitOps Demo — Step-by-Step Guide

**Red Hat PS Team | Strategic Customer Technical Briefing**  
AAP 2.6.0 on OpenShift 4.18.20 | May 2026

---

## Session Variables

Throughout this guide, generated tokens, URLs, and passwords are saved to shell
environment variables. Run every `export` command in the **same terminal session**
you use for the rest of the setup.

A quick reference of all variables set during the demo:

| Variable | Set in | Purpose |
|---|---|---|
| `AAP_ADMIN_PASS` | Lab Credentials | AAP UI login, EDA credential, token generation |
| `OCP_SA_TOKEN` | Section 1 Step 2 | Pasted into the AAP OCP credential |
| `OCP_API_URL` | Section 1 Step 3 | Pasted into the AAP OCP credential |
| `AAP_MICROSERVICE_TOKEN` | Section 2 Step 4 | Pasted into the OCP Secret for the microservice |
| `EDA_WEBHOOK_URL` | Section 5 | GitHub Webhook Payload URL + curl test target |

> Run `echo $VARIABLE_NAME` to display the value whenever a UI field asks you to paste it in.

---

## Lab Credentials

> ⚠️ Passwords are intentionally not stored in this repo. Retrieve them with the commands below and export them before starting.

**OpenShift Console:**  
`https://console-openshift-console.apps.cluster-jx4b7.dynamic.redhatworkshops.io`  
Username: `admin`

```bash
# Retrieve and export the OCP kubeadmin password
# (check your cluster provisioning email if the secret doesn't exist)
export OCP_KUBEADMIN_PASS=$(oc get secret kubeadmin -n kube-system \
  -o jsonpath='{.data.kubeadmin}' | base64 -d)
echo $OCP_KUBEADMIN_PASS
```

**AAP Controller:**  
`https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io`  
Username: `admin`

```bash
# Retrieve and export the AAP admin password from the operator Secret
export AAP_ADMIN_PASS=$(oc get secret -n aap \
  $(oc get secret -n aap -o name | grep admin-password | head -1 | cut -d/ -f2) \
  -o jsonpath='{.data.password}' | base64 -d)
echo $AAP_ADMIN_PASS
```

---

## Scenario Comparison

| | Scenario A — Direct Apply | Scenario B — Approval Gate |
|---|---|---|
| Trigger | `git push` to `main` | `git push` to `main` |
| EDA action | `run_job_template` | `run_workflow_template` |
| AAP component | Job Template | Workflow Template (3 nodes) |
| Approval | None — applies immediately | Email approval via SMTP microservice on OCP |
| Notification | Email / Slack on success | Approval request email + status on completion |

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

Create a `ServiceAccount` with `cluster-admin` in `openshift-monitoring`. AAP will
store the resulting token as a credential to authenticate against the OCP API.

### Step 1 — Create ServiceAccount and ClusterRoleBinding

```bash
oc apply -f ocp/sa-and-crb.yaml
```

### Step 2 — Generate and Export the SA Token

```bash
# Export a 1-year token directly into the session variable
export OCP_SA_TOKEN=$(oc create token aap-gitops-sa \
  -n openshift-monitoring \
  --duration=8760h)

# Verify it was captured (should print a long JWT string)
echo $OCP_SA_TOKEN
```

> **Alternative — non-expiring Secret-based token:**
> ```bash
> cat <<'EOF' | oc apply -f -
> apiVersion: v1
> kind: Secret
> metadata:
>   name: aap-gitops-sa-token
>   namespace: openshift-monitoring
>   annotations:
>     kubernetes.io/service-account.name: aap-gitops-sa
> type: kubernetes.io/service-account-token
> EOF
>
> export OCP_SA_TOKEN=$(oc get secret aap-gitops-sa-token \
>   -n openshift-monitoring \
>   -o jsonpath='{.data.token}' | base64 -d)
> echo $OCP_SA_TOKEN
> ```

### Step 3 — Export the API Server URL

```bash
export OCP_API_URL=$(oc whoami --show-server)
echo $OCP_API_URL
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

In AAP: **Credentials → Add**, using type `OCP Cluster (SA Token)`.

| Field | Value |
|---|---|
| Name | `ocp-demo-cluster` |
| Organization | `Default` |
| Credential Type | `OCP Cluster (SA Token)` |
| OCP API Server URL | run `echo $OCP_API_URL` and paste the output |
| OCP SA Bearer Token | run `echo $OCP_SA_TOKEN` and paste the output |

### Step 3 — Create Git Credential (if repo is private)

| Field | Value |
|---|---|
| Name | `github-gitops-repo` |
| Credential Type | `Source Control` |
| Username | your GitHub username |
| Password/Token | GitHub Personal Access Token (repo scope) |

### Step 4 — Generate and Export the AAP Service Token (Scenario B)

This token is used by the email-approver microservice to call the AAP approval API.

```bash
# Use $AAP_ADMIN_PASS exported from the Lab Credentials section above
export AAP_MICROSERVICE_TOKEN=$(curl -sk -X POST \
  "https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io/api/v2/users/1/tokens/" \
  -H "Content-Type: application/json" \
  -u admin:${AAP_ADMIN_PASS} \
  -d '{"description": "email-approver-microservice", "scope": "write"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo $AAP_MICROSERVICE_TOKEN
```

> You will paste `$AAP_MICROSERVICE_TOKEN` into the OCP Secret in Section 11.

### Step 5 — Create SMTP Credential (for email notifications)

Create a custom credential type that injects `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASS` as environment variables — same pattern as the OCP credential type above.

---

## 3. Git Repository Structure

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
│   ├── email-approver-secret.example.yaml  # Secret template (fill in and apply)
│   └── email-approver-deploy.yaml     # Deployment for the approval microservice
└── docs/DEMO_GUIDE.md
```

---

## 4. EDA Rulebooks

> Activate **only one rulebook at a time**. Toggle between Scenario A and B in EDA UI.

See `rulebooks/scenario-a-direct.yml` and `rulebooks/scenario-b-approval.yml` in this repo.

---

## 5. EDA — Project, Activation & OCP Route

### Step 1 — Create EDA Credential (AAP Controller)

In EDA UI: **Credentials → Create**

| Field | Value |
|---|---|
| Name | `aap-controller-credential` |
| Credential Type | `Red Hat Ansible Automation Platform` |
| URL | `https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io` |
| Username | `admin` |
| Password | run `echo $AAP_ADMIN_PASS` and paste the output |
| SSL Verify | `False` |

### Step 2 — Create EDA Project

| Field | Value |
|---|---|
| Name | `aap-gitops-demo` |
| SCM Type | `Git` |
| SCM URL | `https://github.com/tommeramber/aap-eda-gitops` |
| Branch | `main` |
| SCM Credential | leave empty (public repo) |

### Step 3 — Create Rulebook Activation (Scenario A)

| Field | Value |
|---|---|
| Name | `gitops-scenario-a-direct` |
| Project | `aap-gitops-demo` |
| Rulebook | `scenario-a-direct.yml` |
| Decision Environment | `de-supported` (default) |
| AAP Controller Credential | `aap-controller-credential` |
| Service Name | `eda-gitops-webhook` |

### Step 4 — Expose the EDA Webhook and Export Its URL

```bash
oc apply -f ocp/eda-webhook-route.yaml

# Export the full webhook URL into a session variable
export EDA_WEBHOOK_URL="https://$(oc get route eda-gitops-webhook \
  -n aap -o jsonpath='{.spec.host}')"

echo $EDA_WEBHOOK_URL
# Expected: https://eda-webhook.apps.cluster-jx4b7.dynamic.redhatworkshops.io
```

> You will paste `$EDA_WEBHOOK_URL` as the Payload URL in GitHub Webhooks (Section 7).

---

## 6. Scenario A — Playbook & Job Template

See `playbooks/apply-manifest.yml`.

### Job Template Configuration

| Field | Value |
|---|---|
| Name | `gitops-apply-networkpolicy` |
| Job Type | `Run` |
| Project | `aap-gitops-demo` |
| Playbook | `playbooks/apply-manifest.yml` |
| Inventory | `Demo Inventory` (playbook runs on localhost) |
| Credentials | `ocp-demo-cluster` + SMTP credential |
| Extra Variables: Prompt on Launch | **CHECKED** |

> ⚠️ **"Prompt on Launch" for Extra Variables is mandatory.** Without it, EDA cannot
> pass `repo_url`, `commit_sha`, and `changed_files` to the playbook at runtime.

---

## 7. GitHub Webhook Configuration

### Step 1 — Add Webhook

In GitHub: **Repository → Settings → Webhooks → Add webhook**

| Field | Value |
|---|---|
| Payload URL | run `echo $EDA_WEBHOOK_URL` and paste the output |
| Content type | `application/json` |
| Secret | leave blank for demo |
| Which events? | Just the **push** event |
| Active | Checked |

### Step 2 — Test with curl

```bash
# Uses $EDA_WEBHOOK_URL exported in Section 5
curl -sk -X POST ${EDA_WEBHOOK_URL} \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -d '{
    "ref": "refs/heads/main",
    "after": "abc123def456",
    "repository": {
      "clone_url": "https://github.com/tommeramber/aap-eda-gitops"
    },
    "commits": [{
      "modified": ["ocp/sa-and-crb.yaml"]
    }]
  }'
```

### Step 3 — End-to-End Verification

```bash
# 1. Edit any .yaml file in the repo and commit to main
# 2. EDA UI: Rulebook Activations → gitops-scenario-a-direct → History
#    Should fire within seconds
# 3. AAP UI: Jobs → gitops-apply-networkpolicy should appear
# 4. OCP: oc get networkpolicy -A  (modified policy should appear)
```

---

## 8. Scenario B — AAP Workflow Template

The workflow chains three nodes: send approval email → approval gate → apply + notify.

### Create Workflow Template

In AAP: **Templates → Add → Workflow Template**

| Field | Value |
|---|---|
| Name | `gitops-approval-workflow` |
| Organization | `Default` |
| Extra Variables: Prompt on Launch | **CHECKED** |

### Workflow Nodes (Workflow Visualizer)

| Node | Type | Name / Config | Connection |
|---|---|---|---|
| Node 1 | Job Template | `gitops-send-approval-request` | Start |
| Node 2 | Approval | `Approve GitOps Change` (timeout: 24h) | On Success from Node 1 |
| Node 3 | Job Template | `gitops-apply-networkpolicy` | On Approval from Node 2 |

### Job Template: gitops-send-approval-request

| Field | Value |
|---|---|
| Playbook | `playbooks/send-approval-request.yml` |
| Credentials | `ocp-demo-cluster` + SMTP credential |
| Extra Variables: Prompt on Launch | **CHECKED** |

> **Note on `tower_workflow_job_id`:** AAP automatically injects this variable inside
> a Workflow. The playbook uses it to locate the pending approval node ID via the
> REST API and embed it in the email so the microservice can approve the right node.

---

## 9. Scenario B — Approval Request Playbook

See `playbooks/send-approval-request.yml`.

Key behaviour: embeds `WFJ-<workflow_job_id>/<approval_node_id>` in the email body
so the microservice can target the exact approval node when the approver replies.

---

## 10. Email Approval Microservice (Python)

See `microservice/app.py`, `microservice/Dockerfile`, `microservice/requirements.txt`.

```bash
# Build and push (replace YOUR_ORG with your Quay/registry org)
podman build -t quay.io/YOUR_ORG/email-approver:latest microservice/
podman login quay.io
podman push quay.io/YOUR_ORG/email-approver:latest
```

---

## 11. OCP Deployment for the Microservice

### Step 1 — Fill in the Secret

```bash
cp ocp/email-approver-secret.example.yaml ocp/email-approver-secret.yaml
```

Edit `ocp/email-approver-secret.yaml` and set the following values.
Use `echo $VARIABLE` to retrieve any value generated earlier in this guide:

| Secret key | Value |
|---|---|
| `IMAP_HOST` | your IMAP server (e.g. `imap.gmail.com`) |
| `IMAP_USER` | the inbox address that receives approval replies |
| `IMAP_PASS` | IMAP password or Gmail App Password |
| `AAP_BASE_URL` | `https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io` |
| `AAP_TOKEN` | run `echo $AAP_MICROSERVICE_TOKEN` and paste the output |
| `AAP_VERIFY_SSL` | `false` |

> ⚠️ `ocp/email-approver-secret.yaml` is in `.gitignore` — never commit it.

### Step 2 — Deploy

```bash
oc apply -f ocp/email-approver-secret.yaml -n aap
oc apply -f ocp/email-approver-deploy.yaml -n aap
oc rollout status deployment/email-approver -n aap
oc logs -f deployment/email-approver -n aap
```

> ⚠️ The microservice needs outbound **TCP 993** to your IMAP server.
> Verify OCP NetworkPolicies and egress rules in the `aap` namespace allow this.

---

## 12. Demo Walkthrough Checklist

### Pre-Demo — Session Variables Check

Before anything else, confirm all variables are set in your terminal:

```bash
echo "AAP_ADMIN_PASS      = $AAP_ADMIN_PASS"
echo "OCP_SA_TOKEN        = ${OCP_SA_TOKEN:0:40}..."
echo "OCP_API_URL         = $OCP_API_URL"
echo "AAP_MICROSERVICE_TOKEN = ${AAP_MICROSERVICE_TOKEN:0:20}..."
echo "EDA_WEBHOOK_URL     = $EDA_WEBHOOK_URL"
```

### Pre-Demo — Infrastructure Check

| # | Task | Verify |
|---|---|---|
| 1 | OCP: `aap-gitops-sa` SA exists | `oc get sa aap-gitops-sa -n openshift-monitoring` |
| 2 | AAP: Custom credential type `OCP Cluster (SA Token)` | AAP UI → Administration → Credential Types |
| 3 | AAP: `ocp-demo-cluster` credential | AAP UI → Credentials |
| 4 | AAP: `aap-gitops-demo` project synced | AAP UI → Projects → Status: Successful |
| 5 | AAP: `gitops-apply-networkpolicy` job template | AAP UI → Templates |
| 6 | AAP: `gitops-send-approval-request` job template | AAP UI → Templates |
| 7 | AAP: `gitops-approval-workflow` workflow (3 nodes) | AAP UI → Templates → Visualizer |
| 8 | EDA: `aap-controller-credential` exists | EDA UI → Credentials |
| 9 | EDA: `gitops-scenario-a-direct` activation Running | EDA UI → Rulebook Activations |
| 10 | OCP: EDA Route accessible | `curl -sk ${EDA_WEBHOOK_URL}` (no connection refused) |
| 11 | GitHub: webhook last delivery = 200 | Repo → Settings → Webhooks |
| 12 | **Scenario B only:** `email-approver` pod Running | `oc get pods -n aap \| grep email-approver` |
| 13 | **Scenario B only:** microservice token valid | `oc logs deployment/email-approver -n aap` |

---

### Scenario A — Live Demo Steps

| Step | Action | Show the Audience |
|---|---|---|
| 1 | Confirm `gitops-scenario-a-direct` activation is Running | EDA UI → Rulebook Activations |
| 2 | Edit a NetworkPolicy YAML in the Git repo | GitHub browser UI |
| 3 | Commit directly to main (or merge a PR) | GitHub commit confirmation |
| 4 | Watch EDA activation history fire within seconds | EDA UI → History |
| 5 | Watch AAP job `gitops-apply-networkpolicy` start | AAP UI → Jobs → Running |
| 6 | Show job output: git clone, then k8s apply task | Job details → Output tab |
| 7 | Show the NetworkPolicy appeared in OCP | OCP → Networking → NetworkPolicies |
| 8 | Show notification email received | Email inbox |

---

### Scenario B — Live Demo Steps

| Step | Action | Show the Audience |
|---|---|---|
| 1 | Deactivate `scenario-a`, activate `scenario-b-approval` | EDA UI → toggle activations |
| 2 | Edit and push a NetworkPolicy YAML to main | GitHub UI |
| 3 | Watch EDA fire → AAP Workflow starts | EDA + AAP UI side by side |
| 4 | Show Workflow: Node 1 running (`send-approval-request`) | AAP Workflow Visualizer |
| 5 | Show approval request email in approver inbox | Email client |
| 6 | Reply with single word: `approved` | Email client |
| 7 | Show microservice log: `"Approved id=X HTTP 204"` | `oc logs -f deployment/email-approver -n aap` |
| 8 | Watch Approval node turn green, Node 3 start | AAP Workflow Visualizer |
| 9 | Show NetworkPolicy applied in OCP + status email | OCP Console + email |

---

### AAP Workflow Approval API Reference

```bash
# List all pending approvals
curl -sk \
  "https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io/api/v2/workflow_approvals/?status=pending" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}"

# Approve a specific approval node (replace 42 with the real ID)
curl -sk -X POST \
  "https://demo-aap-aap.apps.cluster-jx4b7.dynamic.redhatworkshops.io/api/v2/workflow_approvals/42/approve/" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

*Red Hat PS Team — May 2026*
