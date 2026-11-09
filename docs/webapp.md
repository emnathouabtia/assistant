# B1 — Web app Bicep template

Owner: Arij

## What it creates

`app/infra/modules/webapp.bicep` is a Bicep template that creates 2 Azure resources:

- an **App Service plan** (`Microsoft.Web/serverfarms`): the Linux server the app runs on, and its price tier
- a **Web App** (`Microsoft.Web/sites`): the application running on that plan

The user never writes Bicep. The assistant fills the template's parameters from the user's request (through `webapp_params`), and B3 deploys it after the user confirms.

## Parameters

| Parameter | Default | Allowed values | Meaning |
| --- | --- | --- | --- |
| `appName` | none (required) | 3 to 40 characters | Base name of the app |
| `location` | the resource group's region | any region allowed by the subscription | Azure region |
| `tags` | `{}` | any object | Tags, e.g. `createdBy: ai-assistant` |
| `skuName` | `B1` | `F1`, `B1` | Plan price tier |
| `linuxFxVersion` | `PYTHON|3.12` | `PYTHON|3.12`, `NODE|20-lts` | Runtime |

Computed names:
- plan: `asp-<appName>`
- web app: `<appName>-<uniqueString(resourceGroup().id)>`. Web app names must be unique across all of Azure, and the suffix stays the same for the same resource group, so redeploying reuses the same app.

## Outputs

| Output | Example | Used by |
| --- | --- | --- |
| `siteName` | `arijdemo-nfdd65fo7q6vm` | C1 (pipeline deploy target) |
| `defaultHostName` | `arijdemo-nfdd65fo7q6vm.azurewebsites.net` | B3 (shown to the user in the status) |

## Secure defaults

- `httpsOnly: true`: no unencrypted HTTP
- `minTlsVersion: '1.2'`: no old, weak TLS versions
- `ftpsState: 'Disabled'`: no FTP uploads (code is deployed by the pipeline)
- `identity: SystemAssigned`: the app has its own managed identity, so it can later read Key Vault secrets without a password
- `@allowed` on `skuName`: Azure itself refuses expensive tiers (second safety line after A3's guardrails)

## Registry entry (webapp_params)

`app/infra/webapp_registry.py` translates a `ResourceSpec` (from A1's intent) into the template's parameters, and registers it for `ResourceType.webapp`:

- `name` → `appName`
- `region` → `location`
- `sku` → `skuName` (default `B1`)
- `runtime` (`python` / `node`, any case) → `linuxFxVersion` (default `PYTHON|3.12`)
- tags: `COMMON_TAGS` (`createdBy: ai-assistant`)

B3 finds it with `REGISTRY[ResourceType.webapp]`.

## How to test

Unit tests (parameter mapping + template compiles):

```bash
pytest tests/test_infra.py -v
```

Manual test on Azure (in a throwaway resource group, then delete it):

```bash
az deployment group validate --resource-group <rg> --template-file app/infra/modules/webapp.bicep --parameters appName=demo skuName=B1 location=spaincentral
az deployment group what-if  --resource-group <rg> --template-file app/infra/modules/webapp.bicep --parameters appName=demo skuName=B1 location=spaincentral
az deployment group create   --resource-group <rg> --template-file app/infra/modules/webapp.bicep --parameters appName=demo skuName=B1 location=spaincentral
```

Tested on 2026-11-09: deploy succeeded in about 33 s, redeploy created nothing new (idempotent), and `skuName=P3v3` was refused at validation.

## Known limits

- **Region:** student subscriptions cannot deploy to `westeurope`. App Service only worked in `spaincentral`.
- **Quota:** F1 = 0 and B1 = 0 in `francecentral` and `germanywestcentral`. Only B1 in `spaincentral` passed, so the default SKU is `B1`.
- **What-if noise:** on a redeploy, what-if reports changes that don't really happen (`freeOfferExpirationTime`, `siteConfig.ftpsState`, `minTlsVersion`, `netFrameworkVersion`, `localMySqlEnabled`).
- **Cost:** B1 is billed by the hour while the plan exists. Delete test resource groups right after testing.