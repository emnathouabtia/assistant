# B2 — Data and security Bicep templates

Owner: Nour

## What it creates

Three Bicep templates in `app/infra/modules/`, plus their registry entries in
`app/infra/data_registry.py`:

| Template | Resources | Type |
| --- | --- | --- |
| `storage.bicep` | Storage account (`Microsoft.Storage/storageAccounts`, `StorageV2`) | `storage` |
| `sql.bicep` | SQL server + one database (`Microsoft.Sql/servers`, `.../databases`) | `sql` |
| `keyvault.bicep` | Key Vault (`Microsoft.KeyVault/vaults`) | `keyvault` |

The user never writes Bicep. A1's intent gives a `ResourceSpec`, the registry entry turns it into
template parameters, and B3 plans and deploys it after the user confirms.

## Parameters

| Template | Parameter | Default | Allowed values | Meaning |
| --- | --- | --- | --- | --- |
| all | `baseName` | none (required) | storage 3–8, keyvault 3–6, sql 3–20 | Name the generated name is built from |
| all | `location` | the resource group's region | any region the subscription allows | Azure region |
| all | `tags` | `{}` | any object | `createdBy: ai-assistant` |
| storage | `skuName` | `Standard_LRS` | `Standard_LRS` | Redundancy |
| sql | `adminLogin` | `sqladminuser` | any string | Server administrator login |
| sql | `adminPassword` | **none — required** | any string | `@secure()`, supplied by B3 at deploy time |
| sql | `dbSku` | `Basic` | `Basic` | Database price tier |
| keyvault | `skuName` | `standard` | `standard` | Vault tier |
| keyvault | `tenantId` | the deployment's tenant | any tenant id | Tenant that owns the vault |

Computed names (each one includes `uniqueString(resourceGroup().id)`, so redeploying in the same
resource group reuses the same resource):

| Resource | Name | Length |
| --- | --- | --- |
| Storage account | `st<baseName><uniqueString>` | 23 max (limit 24) |
| SQL server | `sql-<baseName>-<uniqueString>` | 38 max (limit 63) |
| SQL database | `<baseName>-db` | — |
| Key Vault | `kv-<baseName>-<uniqueString>` | 23 max (limit 24) |

## Outputs

These are exactly the names B3 reads after a deployment.

| Template | Output | Example | Used by |
| --- | --- | --- | --- |
| storage | `storageAccountName` | `stshopx7k2nfdd65fo7q6vm` | B3 (status) |
| storage | `blobEndpoint` | `https://stshopx7k2....blob.core.windows.net/` | B3 (status) |
| sql | `serverFqdn` | `sql-shop-x7k2.database.windows.net` | B3 (status) |
| sql | `databaseName` | `shop-db` | B3 (status) |
| keyvault | `vaultName` | `kv-shop-x7k2nfdd65fo7q6vm` | B3 (status) |
| keyvault | `vaultUri` | `https://kv-shop-....vault.azure.net/` | B3 (status) |

## Secure defaults

Storage
- `supportsHttpsTrafficOnly: true` — no plain HTTP
- `minimumTlsVersion: 'TLS1_2'`
- `allowBlobPublicAccess: false` — anonymous blob access is off
- `@allowed(['Standard_LRS'])` — Azure refuses any other redundancy

SQL
- `minimalTlsVersion: '1.2'`
- `adminPassword` is `@secure()`, has **no default**, and is never written in the registry
- **No firewall rule is added.** This is deliberate: nothing can connect until you add your own
  IP (`az sql server firewall-rule create`). The plan warns that the server allows Azure public
  access, which is acceptable for the sandbox only
- `@allowed(['Basic'])` — the cheapest tier, and the only one A3's guardrails allow

Key Vault
- `enableRbacAuthorization: true` — no access policies; permissions come from role assignments
- `enableSoftDelete: true`, 7-day retention — a deleted vault can be recovered
- `publicNetworkAccess: 'Enabled'` — the sandbox has no private endpoint
- `@allowed(['standard'])`

## Registry entry (data_registry.py)

`app/infra/data_registry.py` maps a `ResourceSpec` to template parameters:

| Field | Storage | SQL | Key Vault |
| --- | --- | --- | --- |
| `name` | `baseName`, cleaned, max 8 | `baseName`, cleaned, max 20 | `baseName`, cleaned, max 6 |
| `region` | `location` | `location` | `location` |
| `sku` | `skuName` (default `Standard_LRS`) | `dbSku` (default `Basic`) | `skuName` (default `standard`) |
| — | `tags` | `tags` | `tags` |

`base_name()` cleans the name down to lowercase ASCII letters and digits, truncates it to the
template's limit, and pads it with `x` to 3 characters so `@minLength(3)` always passes.

**The SQL entry never contains `adminPassword`.** B3 generates a random password at deploy time
and passes it only through a temporary parameters file that is deleted afterwards.

`app/infra/__init__.py` imports every registry module, so `import app.infra.deploy` alone
fills `REGISTRY`. Before this, B3 saw an empty registry in production and only its mocked tests
hid the problem.

## The SQL password decision

Option 1 is implemented: B3 generates the password, passes it once through the parameters file,
and shows it to the user exactly once in the final status with a message to save it.

Options considered and rejected for the MVP:
- store it in Key Vault: needs a role assignment and a second deployment step;
- use a Microsoft Entra administrator instead of a password: the most secure, the most work.

The production approach is the Entra administrator. Say so in the report.

## How to test

Unit tests — parameter mapping, the registry, and the compiled templates:

```bash
pytest tests/test_data_infra.py -v