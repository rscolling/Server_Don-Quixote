# BOB Helm Chart (Alpha)

A Kubernetes Helm chart for deploying BOB the orchestrator + ChromaDB. Lives inside the BOB monorepo at `helm/`.

**Status:** Alpha — templates only, not production-tested. The home server prototype proves the architecture; this chart is the prep work for the AWS Kubernetes migration on the roadmap. A future maintainer should run it through `helm lint`, `kubeval`, and an actual cluster before relying on it.

---

## What This Deploys

- **bob** — the orchestrator Deployment + Service (chat port 8100, MCP port 8108)
- **chromadb** — the shared memory vector store (port 8000)
- A PVC for BOB's persistent SQLite data (audit log, scheduler, checkpointer, cost tracker, bus offline queue)
- A PVC for ChromaDB's vector data
- A ConfigMap for BOB's MCP client config (`mcp_servers.json`)
- A ServiceAccount for BOB's pod
- An optional Ingress (disabled by default)

---

## Quick Start

```bash
# 1. Create a Kubernetes secret with your API keys (recommended)
kubectl create secret generic bob-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=NTFY_TOKEN=tk_...

# 2. Install the chart
helm install bob ./helm \
  --set bob.image.repository=YOUR_REGISTRY/bob-orchestrator \
  --set bob.image.tag=v1.0.0 \
  --set bob.existingSecret=bob-secrets

# 3. Check the pods
kubectl get pods -l app.kubernetes.io/name=bob

# 4. Forward the chat port locally to test
kubectl port-forward svc/bob-bob 8100:8100
curl http://localhost:8100/health
```

---

## Configuration

All knobs are in `values.yaml`. The most important ones to override:

```yaml
bob:
  image:
    repository: your-registry/bob-orchestrator
    tag: v1.0.0
  existingSecret: bob-secrets   # Recommended over inline secrets
  env:
    BOB_LLM_PROVIDER: anthropic
    DAILY_BUDGET_USD_TOTAL: "10.00"
    BOB_PERSONALITY: sardonic
```

For a full list of overridable values, see `values.yaml` — every setting is documented inline.

---

## Honest Caveats (Alpha Status)

This chart is **untested in a real cluster**. Things that almost certainly need adjustment:

1. **The container runs as root.** The current Dockerfile doesn't have a non-root user. The chart's `securityContext.runAsNonRoot` is set to `false` to match. Both should be fixed before production.

2. **Single replica only.** APScheduler uses a SQLite jobstore that can't be shared across pods. If you scale `replicaCount > 1`, two pods will fire the same scheduled job twice. Fix is to switch the scheduler to a Postgres jobstore — that's a Tier 3 followup, not part of this chart.

3. **No HPA or PDB.** No HorizontalPodAutoscaler, no PodDisruptionBudget. Add those when you have real load patterns to scale against.

4. **No NetworkPolicy.** Add one to restrict ingress/egress when running in a multi-tenant cluster.

5. **The MCP config is mounted from a ConfigMap as a single file.** This works but feels hacky. A proper solution is a CSI driver or a small init container that templates the file from a Secret. Future maintainer's call.

6. **No leader election.** Background tasks (Gmail poll, ElevenLabs monitor, recovery loop, drain task) all assume a single instance. Multi-pod deployments would need leader election before any of those can be enabled.

7. **The image needs to be built and pushed.** This chart references `bob-orchestrator:latest` by default, which only exists locally on the home server. Build and push to your registry first:
   ```bash
   docker build -t YOUR_REGISTRY/bob-orchestrator:v1.0.0 .
   docker push YOUR_REGISTRY/bob-orchestrator:v1.0.0
   ```

8. **No tests.** A real chart ships with `helm test` hooks. Add when you have a testing strategy.

---

## Lint

To check the templates render without errors:

```bash
cd helm
helm lint .
helm template bob . --debug > /tmp/bob-rendered.yaml
```

The chart should render without errors against the default values. Real cluster deployment requires the caveats above to be addressed.

---

## What's NOT in This Chart

- **The voice service** (`bob-voice`). It's a separate component that talks to BOB over HTTP. A second chart or a sub-chart would deploy it. Not in scope for the alpha.
- **The message bus.** External component. The chart assumes it exists at `MESSAGE_BUS_URL` (default empty, BOB degrades gracefully).
- **The debate arena agents** (PM, RA, CE, QA). These are separate containers in the home server prototype. The full vision deploys them as their own Deployments — Tier 3 followup.
- **ntfy, Langfuse, Uptime Kuma.** External observability components. BOB references them but doesn't ship them.

---

## License

MIT, same as BOB. See the parent repo's LICENSE.
