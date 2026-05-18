# AAP + EDA GitOps Demo — Step-by-Step Guide

**Red Hat PS Team | Strategic Customer Technical Briefing**  
AAP 2.6.0 on OpenShift 4.18.20 | May 2026

---

## Session Variables

Run every `export` command in the **same terminal session** you use for the rest of the
setup. All later commands reference these variables — if you open a new terminal, re-export them.

| Variable | Set in | Used in |
|---|---|---|
| `AAP_URL` | Lab Credentials | AAP UI login, REST API calls from terminal, OCP Secret `AAP_BASE_URL` |
| `AAP_CONTROLLER_URL` | Lab Credentials | EDA `aap-controller-credential` URL only — see note below |
| `AAP_CONTROLLER_PASS` | Lab Credentials | EDA `aap-controller-credential` password field |
| `AAP_ADMIN_PASS` | Lab Credentials | AAP UI login, token generation (Section 11) |
| `OCP_SA_TOKEN` | Section 1 Step 2 | AAP OCP credential (Section 2) |
| `OCP_API_URL` | Section 1 Step 3 | AAP OCP credential (Section 2) |
| `EDA_WEBHOOK_URL` | Section 5 Step 4 | GitHub webhook config (Section 7), curl test |
| `AAP_MICROSERVICE_TOKEN` | Section 11 Step 1 | OCP Secret for the email-approver microservice |

> **AAP_URL vs AAP_CONTROLLER_URL — why two URLs?**  
> In AAP 2.6, the Platform Gateway route (from `AnsibleAutomationPlatform` CR) is the unified UI entry point. It
> handles browser traffic but does **not** expose `/api/v2/` — so EDA's rulebook worker
> gets a 404 when it tries to connect. EDA must be pointed at the **Automation
> Controller's own route** (`$AAP_CONTROLLER_URL`) which does serve `/api/v2/`.
> All `/api/v2/` calls (token creation, approval endpoints) go through `$AAP_CONTROLLER_URL`.

> Run `echo $VARIABLE_NAME` any time a UI field asks you to paste a value.

---

## Lab Credentials

> ⚠️ Run the entire block below in your terminal before starting. All variables are
> discovered dynamically — no hardcoded names, no hardcoded domains.
> Re-run this block whenever you open a new terminal session.

```bash
# ── Namespace ────────────────────────────────────────────────────────────────
export AAP_NS="aap"

# ── OCP API URL ──────────────────────────────────────────────────────────────
export OCP_API_URL=$(oc whoami --show-server)

# ── AAP instance names (used to derive secret names) ─────────────────────────
AAP_INSTANCE=$(oc get AnsibleAutomationPlatform -n ${AAP_NS} \
  -o jsonpath='{.items[0].metadata.name}')
CTRL_INSTANCE=$(oc get AutomationController -n ${AAP_NS} \
  -o jsonpath='{.items[0].metadata.name}')

# ── URLs ──────────────────────────────────────────────────────────────────────
# Platform Gateway — AAP UI and browser access
export AAP_URL=$(oc get AnsibleAutomationPlatform -n ${AAP_NS} \
  -o jsonpath='{.items[0].status.URL}')

# Automation Controller — all /api/v2/ calls go here (Gateway returns 404)
export AAP_CONTROLLER_URL=$(oc get AutomationController -n ${AAP_NS} \
  -o jsonpath='{.items[0].status.URL}')

# ── Passwords ─────────────────────────────────────────────────────────────────
# Gateway admin password (AAP UI login)
export AAP_ADMIN_PASS=$(oc get secret ${AAP_INSTANCE}-admin-password \
  -n ${AAP_NS} -o jsonpath='{.data.password}' | base64 -d)

# Controller admin password (EDA credential + token creation)
export AAP_CONTROLLER_PASS=$(oc get secret ${CTRL_INSTANCE}-admin-password \
  -n ${AAP_NS} -o jsonpath='{.data.password}' | base64 -d)

# ── Verify everything ─────────────────────────────────────────────────────────
echo "OCP_API_URL         = $OCP_API_URL"
echo "AAP_URL             = $AAP_URL"
echo "AAP_CONTROLLER_URL  = $AAP_CONTROLLER_URL"
echo "AAP_ADMIN_PASS      len=${#AAP_ADMIN_PASS}"
echo "AAP_CONTROLLER_PASS len=${#AAP_CONTROLLER_PASS}"
echo ""
# All lengths must be > 0. If any URL is empty the CR status field isn't populated yet —
# wait for the operator to finish reconciling and re-run.

# ── Sanity-check: Controller API must return HTTP 200 ─────────────────────────
curl -sk -o /dev/null -w "Controller /api/v2/config/ → HTTP %{http_code}\n" \
  "${AAP_CONTROLLER_URL}/api/v2/config/" \
  -u "admin:${AAP_CONTROLLER_PASS}"
```

> **The following variables are set later** as their dependencies are created:
> - `OCP_SA_TOKEN` — after the ServiceAccount is created (Section 1)
> - `EDA_WEBHOOK_URL` — after the EDA activation and Route are up (Section 5)
> - `AAP_MICROSERVICE_TOKEN` — after token generation (Section 11)

> Log in to the OCP Console with `admin` and the password from your workshop portal
> before running any `oc` commands above.

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
2. [AAP — Core Credentials & Project](#2-aap--core-credentials--project)
3. [Git Repository Structure](#3-git-repository-structure)
4. [EDA Rulebooks](#4-eda-rulebooks)
5. [EDA — Project, Activation & OCP Route](#5-eda--project-activation--ocp-route)
6. [Scenario A — Job Template & SMTP Credential](#6-scenario-a--job-template--smtp-credential)
7. [GitHub Webhook Configuration](#7-github-webhook-configuration)
8. [Scenario B — AAP Workflow Template](#8-scenario-b--aap-workflow-template)
9. [Scenario B — Approval Request Playbook](#9-scenario-b--approval-request-playbook)
10. [Email Approval Microservice — Build & Push](#10-email-approval-microservice--build--push)
11. [Scenario B — OCP Deployment & Token](#11-scenario-b--ocp-deployment--token)
12. [Demo Walkthrough Checklist](#12-demo-walkthrough-checklist)

---

## 1. OCP — Service Account Setup

Create a `ServiceAccount` with `cluster-admin` in `openshift-monitoring`.
AAP stores the resulting token as a credential to authenticate against the OCP API.

### Step 1 — Create ServiceAccount and ClusterRoleBinding

```bash
oc apply -f ocp/sa-and-crb.yaml

# Verify
oc get sa aap-gitops-sa -n openshift-monitoring
```

### Step 2 — Generate and Export the SA Token

```bash
export OCP_SA_TOKEN=$(oc create token aap-gitops-sa \
  -n openshift-monitoring \
  --duration=8760h)

# Verify — should print a JWT (long string starting with "eyJ")
echo "${OCP_SA_TOKEN:0:40}..."
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
> # Wait a few seconds for the token to be populated, then export
> export OCP_SA_TOKEN=$(oc get secret aap-gitops-sa-token \
>   -n openshift-monitoring \
>   -o jsonpath='{.data.token}' | base64 -d)
> echo "${OCP_SA_TOKEN:0:40}..."
> ```

### Step 3 — Export the OCP API Server URL

```bash
export OCP_API_URL=$(oc whoami --show-server)
echo $OCP_API_URL
# Expected: https://api.<your-cluster-domain>:6443
```

---

## 2. AAP — Core Credentials & Project

> **What belongs here:** only the credentials needed to get AAP talking to OCP and Git.
> Email notifications for Scenario A are handled by AAP's built-in Notification system (Section 6) — no SMTP credential type needed here.
> The SMTP credential for Scenario B's approval email is created in Section 8.
> The microservice token (for Scenario B) is generated in Section 11.

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
| OCP API Server URL | `echo $OCP_API_URL` → paste output |
| OCP SA Bearer Token | `echo $OCP_SA_TOKEN` → paste output |

### Step 3 — Create Git Credential (only if repo is private)

This repo is public — skip this step unless you forked it to a private repo.

| Field | Value |
|---|---|
| Name | `github-gitops-repo` |
| Credential Type | `Source Control` |
| Username | your GitHub username |
| Password/Token | GitHub Personal Access Token (repo scope) |

### Step 4 — Create AAP Project

In AAP: **Projects → Add**

| Field | Value |
|---|---|
| Name | `aap-gitops-demo` |
| Source Control Type | `Git` |
| Source Control URL | `https://github.com/tommeramber/aap-eda-gitops` |
| Source Control Branch | `main` |
| Update Revision on Launch | Checked |
| Source Control Credential | leave empty (public repo) |

Wait for the sync status to show **Successful** before continuing.

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
├── collections/requirements.yml
├── microservice/
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── ocp/
│   ├── sa-and-crb.yaml
│   ├── eda-webhook-route.yaml
│   ├── email-approver-secret.example.yaml
│   └── email-approver-deploy.yaml
└── docs/DEMO_GUIDE.md
```

---

## 4. EDA Rulebooks

> Activate **only one rulebook at a time**. Toggle in EDA UI when switching scenarios.

See `rulebooks/scenario-a-direct.yml` and `rulebooks/scenario-b-approval.yml`.

---

## 5. EDA — Project, Activation & OCP Route

### Step 1 — Create EDA Credential (AAP Controller)

In EDA UI: **Credentials → Create**

| Field | Value |
|---|---|
| Name | `aap-controller-credential` |
| Credential Type | `Red Hat Ansible Automation Platform` |
| URL | `echo $AAP_CONTROLLER_URL` → paste output |
| Username | `admin` |
| Password | `echo $AAP_CONTROLLER_PASS` → paste output |
| SSL Verify | `False` (self-signed cert in this lab) |

> ⚠️ **Two common mistakes that cause activation failures:**
>
> | Symptom | Cause | Fix |
> |---|---|---|
> | `404 Not Found /api/v2/config/` | URL points to Platform Gateway | Use `$AAP_CONTROLLER_URL` (AutomationController CR URL) |
> | `401 Unauthorized /api/v2/config/` | Using the gateway admin password | Use `$AAP_CONTROLLER_PASS` (from `${CTRL_INSTANCE}-admin-password` secret) |

### Step 2 — Create EDA Project

In EDA UI: **Projects → Create**

| Field | Value |
|---|---|
| Name | `aap-gitops-demo` |
| SCM Type | `Git` |
| SCM URL | `https://github.com/tommeramber/aap-eda-gitops` |
| Branch | `main` |
| SCM Credential | leave empty (public repo) |

Wait for sync to show **Completed**.

### Step 3 — Decision Environment

Use the default DE. If it is not pre-populated, pull:  
`registry.redhat.io/ansible-automation-platform-26/de-supported-rhel9:latest`

### Step 4 — Create Rulebook Activation (Scenario A)

In EDA UI: **Rulebook Activations → Create**

| Field | Value |
|---|---|
| Name | `gitops-scenario-a-direct` |
| Project | `aap-gitops-demo` |
| Rulebook | `scenario-a-direct.yml` |
| Decision Environment | `de-supported` (default) |
| AAP Controller Credential | `aap-controller-credential` |
| Service Name | `eda-gitops-webhook` |

Wait for the activation status to show **Running**.

### Step 5 — Discover the EDA Service and Expose the Webhook URL

After the activation is Running, AAP creates a Service in the `aap` namespace.
Verify it exists and export the full URL:

```bash
# Verify the Service was created
oc get svc -n aap | grep eda-gitops-webhook

# Apply the Route
oc apply -f ocp/eda-webhook-route.yaml

# Export the full webhook URL
export EDA_WEBHOOK_URL="https://$(oc get route eda-gitops-webhook \
  -n aap -o jsonpath='{.spec.host}')"

# Verify — should print a full https:// URL
echo $EDA_WEBHOOK_URL
```

> If `oc get svc -n aap | grep eda-gitops-webhook` returns nothing, the activation
> may still be starting. Wait 30 seconds and retry.

---

## 6. Scenario A — Job Template & Email Notification

**How email notification works in Scenario A:**  
The `apply-manifest.yml` playbook does **not** send emails directly. Instead, AAP's
built-in Notification system sends success/failure emails natively — no SMTP code in
the playbook, no custom credential type needed for this scenario.

For Scenario B, the approval-request playbook *does* send email directly (because it
must embed the approval reference ID), so SMTP is only configured there (Section 8).

### Step 1 — Configure Gmail SMTP (Google Workspace / App Password)

> **Why Gmail / Google Workspace:** Red Hat uses Google Workspace, so your
> `@redhat.com` address is a Gmail account. You can relay outbound mail through
> `smtp.gmail.com` using a Google **App Password** — a 16-character password Google
> generates for non-OAuth apps.

**Get a Google App Password:**
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   while signed in with your `@redhat.com` account
2. App: **Mail** → Device: **Other** → name it `aap-demo` → click **Generate**
3. Copy the 16-character code — that is your SMTP password

```bash
# Your SMTP settings (used in Steps 2 and 3 below):
# Host:     smtp.gmail.com
# Port:     587
# User:     example@example.com      ← replace with your actual address
# Password: <16-char App Password>
# TLS:      Yes
```

### Step 2 — Create AAP Email Notification (Scenario A success/failure)

In AAP: **Administration → Notifications → Add**

| Field | Value |
|---|---|
| Name | `gitops-email-notification` |
| Type | `Email` |
| Host | `smtp.gmail.com` |
| Port | `587` |
| Username | `example@example.com` *(your sender address)* |
| Password | *(16-char App Password from Step 1)* |
| Use TLS | Yes |
| Sender | `example@example.com` |
| Recipients | `example@example.com` *(address to receive notifications)* |

### Step 3 — Create Job Template

In AAP: **Templates → Add → Job Template**

| Field | Value |
|---|---|
| Name | `gitops-apply-networkpolicy` |
| Job Type | `Run` |
| Project | `aap-gitops-demo` |
| Playbook | `playbooks/apply-manifest.yml` |
| Inventory | `Demo Inventory` (playbook runs on localhost) |
| Credentials | `ocp-demo-cluster` |
| Extra Variables: Prompt on Launch | **CHECKED** |

> ⚠️ **"Prompt on Launch" is mandatory.** Without it, EDA cannot pass `repo_url`,
> `commit_sha`, and `changed_files` to the playbook at runtime.

### Step 4 — Attach Notification to Job Template

In the `gitops-apply-networkpolicy` Job Template → **Notifications** tab:

- Enable `gitops-email-notification` on **Success**
- Enable `gitops-email-notification` on **Failure**

AAP will now automatically email you when the job completes or fails — no playbook
changes needed.

---

## 7. GitHub Webhook Configuration

### Step 1 — Add Webhook

In GitHub: **Repository → Settings → Webhooks → Add webhook**

| Field | Value |
|---|---|
| Payload URL | `echo $EDA_WEBHOOK_URL` → paste output |
| Content type | `application/json` |
| Secret | leave blank for this demo |
| Which events? | Just the **push** event |
| Active | Checked |

### Step 2 — Test the Webhook with curl

```bash
# Uses $EDA_WEBHOOK_URL exported in Section 5
# -o /dev/null suppresses the empty body; -w prints the HTTP status code
curl -sk -X POST "${EDA_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -d '{
    "ref": "refs/heads/main",
    "after": "abc123def456",
    "repository": {
      "clone_url": "https://github.com/tommeramber/aap-eda-gitops"
    },
    "commits": [{"modified": ["ocp/sa-and-crb.yaml"]}]
  }' \
  -o /dev/null -w "HTTP %{http_code}\n"
```

| Result | Meaning |
|---|---|
| `HTTP 200` (no body) | ✅ EDA received the event — check Rulebook Activations → History |
| `HTTP 000` | ❌ Route unreachable — recheck `oc apply -f ocp/eda-webhook-route.yaml` |
| `HTTP 4xx` with JSON body | ❌ EDA rejected the request — paste the body for diagnosis |

### Step 3 — End-to-End Smoke Test

```bash
# 1. Edit any .yaml file in the repo and commit to main
# 2. Watch EDA: Rulebook Activations → gitops-scenario-a-direct → History
#    Should show a new event within seconds
# 3. Watch AAP: Jobs → gitops-apply-networkpolicy should appear
# 4. Verify in OCP:
oc get networkpolicy -A
```

---

## 8. Scenario B — Full Setup

**Why SMTP is needed here (but not in Scenario A):**  
The `send-approval-request.yml` playbook must embed a unique `WFJ-<id>/<approval_node_id>`
reference into the email body so the microservice can approve the right workflow node.
AAP's built-in notification system can't add custom body content, so this email must be
sent by the playbook directly via `community.general.mail`.

### Step 1 — Create SMTP Credential Type

In AAP: **Administration → Credential Types → Add**  
Name: `SMTP (Approval Email)`

**Input Configuration (YAML):**
```yaml
fields:
  - id: smtp_host
    type: string
    label: SMTP Host
  - id: smtp_port
    type: string
    label: SMTP Port
  - id: smtp_user
    type: string
    label: SMTP Username
  - id: smtp_pass
    type: string
    label: SMTP Password
    secret: true
required:
  - smtp_host
  - smtp_user
  - smtp_pass
```

**Injector Configuration (YAML):**
```yaml
env:
  SMTP_HOST: "{{ smtp_host }}"
  SMTP_PORT: "{{ smtp_port }}"
  SMTP_USER: "{{ smtp_user }}"
  SMTP_PASS: "{{ smtp_pass }}"
```

### Step 2 — Create SMTP Credential

In AAP: **Credentials → Add**, using type `SMTP (Approval Email)`.  
Use the same Gmail App Password you generated in Section 6 Step 1.

| Field | Value |
|---|---|
| Name | `smtp-approval` |
| SMTP Host | `smtp.gmail.com` |
| SMTP Port | `587` |
| SMTP Username | `example@example.com` *(your sender address)* |
| SMTP Password | *(16-char App Password)* |

### Step 3 — Create Job Template: gitops-send-approval-request

In AAP: **Templates → Add → Job Template**

| Field | Value |
|---|---|
| Name | `gitops-send-approval-request` |
| Job Type | `Run` |
| Project | `aap-gitops-demo` |
| Playbook | `playbooks/send-approval-request.yml` |
| Inventory | `Demo Inventory` |
| Credentials | `ocp-demo-cluster` + `smtp-approval` |
| Extra Variables: Prompt on Launch | **CHECKED** |

> No `aap_base_url` or token extra_var needed. AAP automatically injects `TOWER_HOST`
> and `TOWER_AUTH_TOKEN` into every job execution environment. The playbook uses these
> directly — no credentials or extra_vars required for the API call.

### Step 4 — Create Workflow Template

In AAP: **Templates → Add → Workflow Template**

| Field | Value |
|---|---|
| Name | `gitops-approval-workflow` |
| Organization | `Default` |
| Extra Variables | see below |
| Extra Variables: Prompt on Launch | **CHECKED** |

Set the following static extra variables in the Workflow Template:

```yaml
approver_email: "tommeramber@gmail.com"    # address that RECEIVES the approval request
reply_to_email: "AAP-DEMO@gmail.com"       # address replies are ROUTED TO (microservice inbox)
```

> **How the email loop works:**
>
> | | Address | Role |
> |---|---|---|
> | SMTP auth (`smtp-approval` credential) | `tommeramber@gmail.com` | Gmail requires sending FROM the authenticated account |
> | `approver_email` | `tommeramber@gmail.com` | Receives the approval request |
> | `reply_to_email` | `AAP-DEMO@gmail.com` | Reply-To header — approver's reply is routed here |
> | `IMAP_USER` (OCP Secret) | `AAP-DEMO@gmail.com` | Microservice polls this inbox |
>
> Gmail sends FROM `tommeramber@gmail.com` but the **Reply-To** header points to `AAP-DEMO@gmail.com`.
> When you click Reply, your mail client uses Reply-To — so the reply lands in `AAP-DEMO@gmail.com`.
> No second SMTP account needed.

### Step 5 — Build Workflow Nodes (Workflow Visualizer)

Open the Workflow Visualizer and add three connected nodes:

| Node | Type | Name / Config | Connection |
|---|---|---|---|
| Node 1 | Job Template | `gitops-send-approval-request` | Start |
| Node 2 | Approval | `Approve GitOps Change` (timeout: 24h) | On Success from Node 1 |
| Node 3 | Job Template | `gitops-apply-networkpolicy` | On Approval from Node 2 |

> **How `tower_workflow_job_id` works:** AAP automatically injects this variable when
> a job template runs inside a Workflow. The `send-approval-request` playbook uses it
> to query the AAP API for the pending approval node ID and embed it in the email body.

### Step 6 — Create Rulebook Activation (Scenario B)

In EDA UI: **Rulebook Activations → Create**

| Field | Value |
|---|---|
| Name | `gitops-scenario-b-approval` |
| Project | `aap-gitops-demo` |
| Rulebook | `scenario-b-approval.yml` |
| Decision Environment | `de-supported` (default) |
| AAP Controller Credential | `aap-controller-credential` |
| Service Name | `eda-gitops-webhook` |

> ⚠️ **Only one activation should be Running at a time.**  
> Before running Scenario B: **Stop** `gitops-scenario-a-direct`, then **Start** `gitops-scenario-b-approval`.  
> Both activations use the same Service Name (`eda-gitops-webhook`) and Route — no Route changes needed.

---

## 9. Scenario B — Approval Request Playbook

See `playbooks/send-approval-request.yml`.

The playbook embeds `WFJ-<workflow_job_id>/<approval_node_id>` in the approval email.
The email-approver microservice parses this tag to call the exact approval node on the
AAP API — without it, the microservice falls back to approving all pending approvals.

---

## 10. Email Approval Microservice — Build & Push

See `microservice/app.py`, `microservice/Dockerfile`, `microservice/requirements.txt`.

```bash
# Build (replace YOUR_ORG with your Quay or internal registry org)
podman build -t quay.io/YOUR_ORG/email-approver:latest microservice/

# Verify the image starts without errors
podman run --rm \
  -e IMAP_HOST=test -e IMAP_USER=test -e IMAP_PASS=test \
  -e AAP_BASE_URL=http://localhost -e AAP_TOKEN=test \
  quay.io/YOUR_ORG/email-approver:latest \
  python3 -c "import app; print('imports OK')" 2>&1 | head -5

# Push
podman login quay.io
podman push quay.io/YOUR_ORG/email-approver:latest
```

---

## 11. Scenario B — OCP Deployment & Token

> This section is only needed for **Scenario B**. Complete Sections 1–7 and verify
> Scenario A works before starting here.

### Step 1 — Generate and Export the AAP Microservice Token

This token allows the email-approver microservice to call the AAP approval API.
It is created here — close to where it is used — not in Section 2.

```bash
# The token endpoint is on the Automation Controller — use $AAP_CONTROLLER_URL and
# $AAP_CONTROLLER_PASS, NOT $AAP_URL (Platform Gateway returns 404 for /api/v2/)

# Step 1a: create the token and capture the full JSON response
AAP_TOKEN_RESPONSE=$(curl -sk -X POST \
  "${AAP_CONTROLLER_URL}/api/v2/tokens/" \
  -H "Content-Type: application/json" \
  -u "admin:${AAP_CONTROLLER_PASS}" \
  -d '{"description": "email-approver-microservice", "scope": "write"}')

# Step 1b: inspect the response — should show a JSON object with a "token" field
echo "$AAP_TOKEN_RESPONSE" | python3 -m json.tool

# Step 1c: extract and export the token value
export AAP_MICROSERVICE_TOKEN=$(echo "$AAP_TOKEN_RESPONSE" | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

# Step 1d: verify it was captured (should print a non-empty string)
echo "AAP_MICROSERVICE_TOKEN length: ${#AAP_MICROSERVICE_TOKEN}"
```

> If Step 1b shows an HTML 404 page → you used `$AAP_URL` instead of `$AAP_CONTROLLER_URL`.  
> If Step 1b shows `401 Unauthorized` → check `echo $AAP_CONTROLLER_PASS` is non-empty.

### Step 2 — Generate and Apply the OCP Secret

Set your IMAP credentials, then let `sed` fill everything else from the session variables:

```bash
# Set IMAP variables (the only values you need to type manually)
export IMAP_HOST="imap.gmail.com"
export IMAP_USER="example@example.com"   # inbox that receives approval replies
export IMAP_PASS="your-app-password"     # Gmail App Password

# Generate the secret file — sed substitutes all placeholders from exported variables
sed \
  -e "s|__AAP_CONTROLLER_URL__|${AAP_CONTROLLER_URL}|g" \
  -e "s|__AAP_MICROSERVICE_TOKEN__|${AAP_MICROSERVICE_TOKEN}|g" \
  -e "s|__IMAP_HOST__|${IMAP_HOST}|g" \
  -e "s|__IMAP_USER__|${IMAP_USER}|g" \
  -e "s|__IMAP_PASS__|${IMAP_PASS}|g" \
  ocp/email-approver-secret.example.yaml > ocp/email-approver-secret.yaml

# Verify no placeholders remain (output should be empty)
grep "__.*__" ocp/email-approver-secret.yaml && echo "ERROR: unfilled placeholders!" || echo "OK"

# Apply (this file is in .gitignore — never commit it)
oc apply -f ocp/email-approver-secret.yaml -n aap
```

### Step 3 — Deploy the Microservice

Update `ocp/email-approver-deploy.yaml` with your actual image reference, then:

```bash
oc apply -f ocp/email-approver-deploy.yaml -n aap
oc rollout status deployment/email-approver -n aap

# Tail logs — should show "Email Approval Microservice starting"
oc logs -f deployment/email-approver -n aap
```

> ⚠️ The microservice needs outbound **TCP 993** to your IMAP server.
> If the pod logs show connection timeouts, verify OCP egress NetworkPolicies.

---

## 12. Demo Walkthrough Checklist

### Pre-Demo — Confirm All Session Variables

```bash
echo "AAP_URL               = $AAP_URL"
echo "AAP_CONTROLLER_URL    = $AAP_CONTROLLER_URL"
echo "AAP_CONTROLLER_PASS   = ${AAP_CONTROLLER_PASS:0:6}... (len=${#AAP_CONTROLLER_PASS})"
echo "AAP_ADMIN_PASS        = ${AAP_ADMIN_PASS:0:6}... (len=${#AAP_ADMIN_PASS})"
echo "OCP_SA_TOKEN          = ${OCP_SA_TOKEN:0:40}... (len=${#OCP_SA_TOKEN})"
echo "OCP_API_URL           = $OCP_API_URL"
echo "EDA_WEBHOOK_URL       = $EDA_WEBHOOK_URL"
echo "AAP_MICROSERVICE_TOKEN= ${AAP_MICROSERVICE_TOKEN:0:20}... (len=${#AAP_MICROSERVICE_TOKEN})"
```

Any variable showing `len=0` needs to be re-exported before the demo.

### Pre-Demo — Infrastructure Checklist

| # | Task | Verify |
|---|---|---|
| 1 | OCP: `aap-gitops-sa` SA exists | `oc get sa aap-gitops-sa -n openshift-monitoring` |
| 2 | AAP: `OCP Cluster (SA Token)` credential type | AAP UI → Administration → Credential Types |
| 3 | AAP: `ocp-demo-cluster` credential | AAP UI → Credentials |
| 4 | AAP: `gitops-email-notification` notification | AAP UI → Administration → Notifications |
| 5 | AAP: `aap-gitops-demo` project synced | AAP UI → Projects → Status: Successful |
| 6 | AAP: `gitops-apply-networkpolicy` job template (notification attached) | AAP UI → Templates |
| 7 | EDA: `aap-controller-credential` exists | EDA UI → Credentials |
| 8 | EDA: `gitops-scenario-a-direct` activation Running | EDA UI → Rulebook Activations |
| 9 | OCP: EDA Route responds | `curl -sk -o /dev/null -w "%{http_code}" "${EDA_WEBHOOK_URL}"` (not 000) |
| 10 | GitHub: webhook last delivery = 200 | Repo → Settings → Webhooks |
| *(Scenario B only)* | | |
| 11 | AAP: `smtp-approval` credential created | AAP UI → Credentials |
| 12 | AAP: `gitops-send-approval-request` job template created | AAP UI → Templates |
| 13 | AAP: `gitops-approval-workflow` workflow template (3 nodes) | AAP UI → Templates → Visualizer |
| 14 | EDA: `gitops-scenario-b-approval` activation created | EDA UI → Rulebook Activations |
| 15 | OCP: `email-approver` pod Running | `oc get pods -n aap \| grep email-approver` |
| 16 | Microservice log shows "starting" | `oc logs deployment/email-approver -n aap \| head -5` |

---

### Scenario A — Live Demo Steps

| Step | Action | Show the Audience |
|---|---|---|
| 1 | Confirm `gitops-scenario-a-direct` activation is Running | EDA UI → Rulebook Activations |
| 2 | Edit a NetworkPolicy YAML in the Git repo | GitHub browser UI |
| 3 | Commit directly to main (or merge a PR) | GitHub commit confirmation |
| 4 | Watch EDA activation history fire within seconds | EDA UI → History tab |
| 5 | Watch AAP job `gitops-apply-networkpolicy` start | AAP UI → Jobs → Running |
| 6 | Show job output: git clone step, then k8s apply step | Job details → Output tab |
| 7 | Show the NetworkPolicy appeared in OCP | OCP → Networking → NetworkPolicies |
| 8 | Show notification email received | Email inbox |

---

### Scenario B — How to Trigger and Run

**Before you start:** confirm the microservice is running and the Scenario B activation is up:
```bash
# 1. Switch EDA activations
#    EDA UI → Rulebook Activations → gitops-scenario-a-direct → Stop
#    EDA UI → Rulebook Activations → gitops-scenario-b-approval → Start
#    Wait for status: Running

# 2. Confirm microservice is healthy
oc logs deployment/email-approver -n aap | tail -5
# Should show: "Pending approvals: 0" or "starting" — no errors

# 3. Trigger the workflow by pushing a YAML change to main
#    Either edit demo-manifests/default-allow-all-networkpolicy.yaml on GitHub,
#    or run from your terminal:
git clone https://github.com/tommeramber/aap-eda-gitops /tmp/aap-trigger 2>/dev/null || \
  git -C /tmp/aap-trigger pull
echo "# trigger-$(date +%s)" >> /tmp/aap-trigger/demo-manifests/default-allow-all-networkpolicy.yaml
git -C /tmp/aap-trigger add -A
git -C /tmp/aap-trigger commit -m "demo: trigger Scenario B approval workflow"
git -C /tmp/aap-trigger push
```

**What happens next (automatic):**
1. GitHub webhook fires → EDA `gitops-scenario-b-approval` receives it
2. EDA triggers `gitops-approval-workflow` in AAP
3. Workflow Node 1 runs `gitops-send-approval-request` — sends approval request email
4. Workflow **pauses** at Node 2 (Approval gate) — waiting for human approval

**To approve:**
```bash
# Option A — reply to the email (triggers the microservice automatically)
# Open the approval request email → reply with exactly:   approved

# Option B — approve manually via AAP API (for demo/testing without email)
curl -sk \
  "${AAP_CONTROLLER_URL}/api/v2/workflow_approvals/?status=pending" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}" \
  | python3 -m json.tool
# Find the approval ID, then:
curl -sk -X POST \
  "${AAP_CONTROLLER_URL}/api/v2/workflow_approvals/<ID>/approve/" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}" \
  -H "Content-Type: application/json" -d '{}'
```

**After approval:**
- Workflow Node 3 runs `gitops-apply-networkpolicy` — applies the YAML to OCP
- Verify: `oc get networkpolicy -A`

### Scenario B — Live Demo Steps

| Step | Action | Show the Audience |
|---|---|---|
| 1 | Stop `gitops-scenario-a-direct` → Start `gitops-scenario-b-approval` | EDA UI → Rulebook Activations |
| 2 | Edit and push `demo-manifests/default-allow-all-networkpolicy.yaml` to main | GitHub browser UI |
| 3 | Watch EDA fire → AAP Workflow starts | EDA + AAP UI side by side |
| 4 | Show Workflow Visualizer: Node 1 running, then paused at Node 2 | AAP Workflow Visualizer |
| 5 | Show approval request email in approver inbox | Email client |
| 6 | Reply with single word: `approved` | Email client reply |
| 7 | Show microservice log: `Approved id=X HTTP 204` | `oc logs -f deployment/email-approver -n aap` |
| 8 | Watch Approval node turn green, Node 3 start | AAP Workflow Visualizer |
| 9 | Show NetworkPolicy applied in OCP | `oc get networkpolicy -A` |

---

### AAP Workflow Approval API Reference

```bash
# All /api/v2/ calls go to $AAP_CONTROLLER_URL, not $AAP_URL (Platform Gateway)

# List all pending approvals
curl -sk \
  "${AAP_CONTROLLER_URL}/api/v2/workflow_approvals/?status=pending" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}" \
  | python3 -m json.tool

# Approve a specific approval node (replace 42 with the real ID from the response above)
curl -sk -X POST \
  "${AAP_CONTROLLER_URL}/api/v2/workflow_approvals/42/approve/" \
  -H "Authorization: Bearer ${AAP_MICROSERVICE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

*Red Hat PS Team — May 2026*
