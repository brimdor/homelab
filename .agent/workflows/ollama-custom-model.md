---
description: Add or remove a custom Modelfile-based model (like Echo or Humble) from the Ollama model puller
---

# Add / Remove Custom Ollama Model

> All custom models live in `apps/ollama/`. Script logic is in `templates/_model-*.tpl`, config data is in `values.yaml`.

---

## Adding a New Custom Model

### 1. Create the model template

// turbo
Copy an existing model template as your starting point:

```bash
cp apps/ollama/templates/_model-echo.tpl apps/ollama/templates/_model-<name>.tpl
```

### 2. Edit the new template

Open `apps/ollama/templates/_model-<name>.tpl` and update:

- **Template define name**: Change `"ollama.script.model.echo"` → `"ollama.script.model.<name>"`
- **All `.Values` paths**: Change `.Values.modelPuller.models.custom.echo` → `.Values.modelPuller.models.custom.<name>`
- **Model name references**: Replace `echo` with `<name>` (lowercase) in:
  - Modelfile path (`/tmp/Modelfile.<name>`)
  - `ollama rm <name>`
  - `ollama create <name>`
  - All log messages

### 3. Add config to values.yaml

Add a new block under `modelPuller.models.custom` in `apps/ollama/values.yaml`:

```yaml
modelPuller:
  models:
    custom:
      # ... existing models ...

      <name>:
        enabled: true
        base: "<base-model>:<tag>"     # e.g. "llama3.2:3b"
        contextSize: 64000             # num_ctx parameter
        repeatPenalty: 1.5             # optional
        temperature: 0.7               # optional
        systemPrompt: |
          Your system prompt here...
```

> [!IMPORTANT]
> If the base model isn't already in `modelPuller.models.pull`, add it there too so it gets downloaded first.

### 4. Register in entrypoint

Open `apps/ollama/templates/_entrypoint.tpl` and add the include **before** the `sleep infinity` line:

```
{{ include "ollama.script.model.<name>" . }}
```

### 5. Validate

// turbo
```bash
cd apps/ollama && helm template test . 2>&1 | grep -i "<name>"
```

Confirm the new model's Modelfile and create commands appear in the rendered output.

---

## Removing a Custom Model

### 1. Remove from entrypoint

Delete the `{{ include "ollama.script.model.<name>" . }}` line from `apps/ollama/templates/_entrypoint.tpl`.

### 2. Remove config from values.yaml

Delete the entire `<name>:` block under `modelPuller.models.custom` in `apps/ollama/values.yaml`.

### 3. Delete the template file

// turbo
```bash
rm apps/ollama/templates/_model-<name>.tpl
```

### 4. Clean up base models (optional)

If the removed model's base image is no longer used by any other custom model, remove it from `modelPuller.models.pull` in `values.yaml`.

### 5. Validate

// turbo
```bash
cd apps/ollama && helm template test . 2>&1 | grep -i "<name>"
```

Confirm no references to the removed model remain.

---

## File Reference

| File | Purpose |
|------|---------|
| `apps/ollama/templates/_common.tpl` | Shared utilities (wait, pull_with_retry) |
| `apps/ollama/templates/_model-*.tpl` | One per custom model |
| `apps/ollama/templates/_entrypoint.tpl` | Orchestrates all scripts |
| `apps/ollama/templates/model-puller.yaml` | ConfigMap + Deployment |
| `apps/ollama/values.yaml` | Model configuration data |
