@description('Lowercase letters and digits, 3 to 20 characters')
@minLength(3)
@maxLength(20)
param baseName string

param location string = resourceGroup().location
param tags object = {}
param adminLogin string = 'sqladminuser'

// Required and never defaulted: B3 generates it at deploy time and passes it
// only through a temporary parameters file. It never appears in the registry.
@secure()
param adminPassword string

@description('Basic is the only tier the guardrails allow (cost limit).')
@allowed([
  'Basic'
])
param dbSku string = 'Basic'

var tier = dbSku == 'Basic' ? 'Basic' : 'Standard'

// 'sql-' (4) + baseName (max 20) + '-' (1) + uniqueString (13) = 38, under the 63 character limit.
var serverName = toLower('sql-${baseName}-${uniqueString(resourceGroup().id)}')

resource server 'Microsoft.Sql/servers@2021-11-01' = {
  name: serverName
  location: location
  tags: tags
  properties: {
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    minimalTlsVersion: '1.2'
    // No firewall rule is added on purpose: clients cannot connect until one is.
    publicNetworkAccess: 'Enabled'
  }
}

resource db 'Microsoft.Sql/servers/databases@2021-11-01' = {
  parent: server
  name: '${baseName}-db'
  location: location
  tags: tags
  sku: {
    name: dbSku
    tier: tier
  }
  properties: {
    maxSizeBytes: 2147483648
  }
}

output serverFqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = db.name
