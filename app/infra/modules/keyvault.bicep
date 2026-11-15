@description('Lowercase letters and digits, 3 to 6 characters')
@minLength(3)
@maxLength(6)
param baseName string

param location string = resourceGroup().location
param tags object = {}
param tenantId string = subscription().tenantId

@description('standard is the only tier the guardrails allow (cost limit).')
@allowed([
  'standard'
])
param skuName string = 'standard'

// 'kv-' (3) + baseName (max 6) + '-' (1) + uniqueString (13) = 23, under the 24 character limit.
var vaultName = 'kv-${baseName}-${uniqueString(resourceGroup().id)}'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: skuName
    }
    // RBAC instead of access policies: permissions are granted by role assignment.
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    // The sandbox has no private endpoint; the vault is still RBAC-only.
    publicNetworkAccess: 'Enabled'
  }
}

output vaultName string = kv.name
output vaultUri string = kv.properties.vaultUri
