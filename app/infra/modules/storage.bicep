@description('Lowercase letters and digits, 3 to 8 characters')
@minLength(3)
@maxLength(8)
param baseName string

param location string = resourceGroup().location
param tags object = {}

@description('Standard_LRS is the only redundancy the guardrails allow (cost limit).')
@allowed([
  'Standard_LRS'
])
param skuName string = 'Standard_LRS'

// 'st' (2) + baseName (max 8) + uniqueString (13) = 23, under the 24 character limit.
// The name must be globally unique and lowercase, hence toLower().
var accountName = toLower('st${baseName}${uniqueString(resourceGroup().id)}')

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: accountName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

output storageAccountName string = sa.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
